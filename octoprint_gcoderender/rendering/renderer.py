__author__ = "Erik Heidstra <ErikHeidstra@live.nl>"

import sys, os

from math import *

if sys.platform == "win32" or sys.platform == "darwin":
    
    os.environ["PYSDL2_DLL_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sdl')
    from OpenGL.GL import *
    from OpenGL.GLU import *
    import sdl2
else:
    from pyopengles import *
    # TODO: Define these inside pyopengles
    GL_VERTEX_ARRAY = 0x8074

from gcodeparser import *

from matrix44 import *
from vector3 import *

from PIL import Image
from datetime import datetime

# Default settings for the renderer
DEFAULT_WIDTH = 600
DEFAULT_HEIGHT = 1024
DEFAULT_BED_WIDTH = 365
DEFAULT_BED_DEPTH = 350
DEFAULT_SYNC_OFFSET = float(DEFAULT_BED_WIDTH - 35) / 2
DEFAULT_PART_COLOR = (77./255., 120./255., 190./255.)
DEFAULT_BED_COLOR=  (70./255., 70./255., 70./255.)
DEFAULT_BACKGROUND_COLOR=  (1,1,1)
DEFAULT_CAMERA_POSITION=  (0, -80.0, 100.0)
DEFAULT_CAMERA_MOVEMENT_SPEED = 100.0
DEFAULT_CAMERA_ROTATION=  (radians(45), radians(0), radians(0))
DEFAULT_CAMERA_ROTATION_SPEED = radians(90.0)
DEFAULT_CAMERA_DISTANCE = (-100., -100., 75.)

# Abstract of the renderer class, allow interoperability between linux and win32
#TODO: implement shared logic of win/linux
#TODO: Make a blueprint that makes more sense, functionality should better match to function names for both OpenGL and OpenGLES
class Renderer:
    def __init__(self, verbose = False):
        self.verbose = verbose
        pass
    def initialize(self):
        pass
    def close(self):
        pass
    def renderModel(self, gcodeFile, bringCameraInPosition = False):
        pass
    def clear(self):
        pass
    def save(self, imageFile):
        pass
    def logInfo(self, message):
        #TODO: Actual logging to file
        if self.verbose:
            print "{time} {msg}".format(time=datetime.now(), msg=message)

# To be used on raspberry pi
class RendererOpenGLES(Renderer):
    def __init__(self, verbose = False):
        Renderer.__init__(self, verbose)
        #TODO:Parent class to share all these properties with the OpenGL-renderer
        self.show_window = False
        self.is_initialized = False
        self.is_window_open = False
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.bed_width = DEFAULT_BED_WIDTH
        self.bed_depth = DEFAULT_BED_DEPTH
        self.sync_offset = DEFAULT_SYNC_OFFSET
        self.background_color = DEFAULT_BACKGROUND_COLOR
        self.bed_color = DEFAULT_BED_COLOR
        self.part_color = DEFAULT_PART_COLOR
        self.camera_position = DEFAULT_CAMERA_POSITION
        self.camera_rotation = DEFAULT_CAMERA_ROTATION
        self.gcode_model = None
        self.base_vertices = None
        self.display_list = None
        self.rotation_direction = Vector3()
        self.rotation_speed = DEFAULT_CAMERA_ROTATION_SPEED
        self.movement_direction = Vector3()
        self.movement_speed = DEFAULT_CAMERA_MOVEMENT_SPEED
        self.camera_distance = DEFAULT_CAMERA_DISTANCE # Distance from object
        self.program = None
        self.ctx = None
        self.position_handle = None
        self.color_handle = None
        self.camera_handle = None
                
    def initialize(self, bedWidth, bedDepth, width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT, showWindow = False,  backgroundColor = None, partColor = None, bedColor = None, cameraPosition = None, cameraRotation = None):
        """
        Initializes and configures the renderer
        """

        if self.is_initialized:
            return

        self.bed_width = bedWidth
        self.bed_depth = bedDepth
        self.width = width
        self.height = height
        self.show_window = showWindow

        if backgroundColor:
            self.background_color = backgroundColor
          
        if bedColor:
            self.bed_color = bedColor

        if partColor:
            self.part_color = partColor
            
        if cameraPosition:
            self.camera_position = cameraPosition
        else:
            self.camera_position = (self.bed_width / 2, DEFAULT_CAMERA_POSITION[1], DEFAULT_CAMERA_POSITION[2]) # Move to x-center

        if cameraRotation:
            self.camera_rotation = cameraRotation

        self._openWindow()
        self._setViewportAndPerspective()
        self._setLighting()

        self.is_initialized = True

    def close(self):
        """
        Closes the rendering context. Only call when you are done rendering all images
        """
        if not self.is_initialized or not self.is_window_open:
            return
        
        self.ctx.close()

    def renderModel(self, gcodeFile, bringCameraInPosition = False):
        """
        Renders a gcode file into a preview image.

        bringCameraInPosition: Automatically calculate camera position for a nice angle
        """ 
        if not self.is_initialized or not self.is_window_open:
            return

        # Read the gcode file and get all coordinates
        parser = GcodeParser(verbose = self.verbose)
        self.gcode_model = parser.parseFile(gcodeFile)

        # Deprecated: Sync mode. Distance between parts left and right
        if self.gcode_model.syncOffset > 0:
            self.sync_offset = self.gcode_model.syncOffset
        
        # Get all vertices that define the lines to be drawn from the parser
        self.base_vertices = self._getVertices()

        # Start with a clean slate and draw the bed
        self._clearAll()

        # Configure lights
        self._setLight()

        
        if bringCameraInPosition:
            # Calculate a nice position for the camera and move it there
            self._bringCameraInPosition()
        else:
            # Just move the camera to the predefined (fixed) position
            self._updateCamera()

        # Prepare the lines that should be drawn from the vertices
        self._prepareDisplayList()        
        
        # Draw the lines to the framebuffer
        self._renderDisplayList()

        if self.is_window_open:
            time.sleep(3)


    def clear(self):
        """
        Clears the frame and draws the bed
        """
        if not self.is_initialized or not  self.is_window_open:
            return

        self._clearAll()
        self._renderBed()
    
    def save(self, imageFile):
        """
        Save the framebuffer to a file
        """

        if not self.is_initialized or not self.is_window_open:
            return

        # Create Buffer
        N = self.width*self.height*4
        data = (ctypes.c_uint8*N)()

        # Read all pixel colors
        opengles.glReadPixels(0,0,self.width,self.height,GL_RGBA,GL_UNSIGNED_BYTE, ctypes.byref(data))
        
        # Write raw data to image file
        imgSize = (self.width, self.height)
        img = Image.frombytes('RGBA', imgSize, data)
        img.transpose(Image.FLIP_TOP_BOTTOM).save(imageFile)

    def _initFrameBuffer(self):
        """
        Create a frame buffer object to draw the lines to
        """

        self.fbo = ctypes.c_uint()
        self.color_buf = ctypes.c_uint()
        self.depth_buf = ctypes.c_uint()

        # Framebuffer
        opengles.glGenFramebuffers(1,self.fbo)
        opengles.glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        
        # Colorbuffer
        opengles.glGenRenderbuffers(1,self.color_buf)
        opengles.glBindRenderbuffer(GL_RENDERBUFFER, self.color_buf)
        opengles.glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, self.width, self.height)
        opengles.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, self.color_buf)

        # Depthbuffer
        opengles.glGenRenderbuffers(1, self.depth_buf)
        opengles.glBindRenderbuffer(GL_RENDERBUFFER, self.depth_buf)
        opengles.glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, self.width, self.height)
        opengles.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self.depth_buf)

    def _deinitFrameBuffer(self):
       """
       De-initializes the framebuffer object
       """
       opengles.glDeleteRenderbuffersEXT(1, self.color_buffer)
       opengles.glDeleteRenderbuffersEXT(1, self.depth_buffer)
       opengles.glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, 0)
       opengles.glDeleteFramebuffersEXT(1, self.fbo)

    def _bringCameraInPosition(self):
        """
        Calculates the best position for the camera to bring the entire part into the viewport
        """

        # Check if the gcode model knows the boundaries of the part
        if self.gcode_model.bbox:
            # Find the center of the object and make an estimation of the size of it (the / 75 was found by trial and error to give a nice zoom factor)
            # Take more distance for sync/mirror parts 
            if self.gcode_model.printMode == 'sync':
                object_center = Vector3(self.gcode_model.bbox.cx() + self.sync_offset / 2, self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.gcode_model.bbox.xmax+self.sync_offset - self.gcode_model.bbox.xmin, self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
            elif self.gcode_model.printMode == 'mirror':
                object_center = Vector3(self.bed_width / 2, self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.bed_width - self.gcode_model.bbox.xmin*2, self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
            else:
                object_center = Vector3(self.gcode_model.bbox.cx(), self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.gcode_model.bbox.dx(), self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
        else:
            object_center = Vector3(self.bed_width/2, self.bed_depth/2, 0)
            scale = 1
        
        # Calculate the camera distance
        cam_dist = Vector3(self.camera_distance) * scale
        self.camera_position = (object_center + cam_dist).as_tuple()
        up = (0, 0, 1)

        # Calculate the lookat and projection matrices
        lookat = Matrix44.lookat(object_center, up, self.camera_position)
        projection = Matrix44.perspective_projection_fov(radians(45), float(self.width)/float(self.height), 0.1, 10000.0)

        # Calculate the camera matrix. This matrix translates and rotates all vertices, as such that it looks like the camera is brought in position
        self.camera_matrix = projection * lookat

        ccam = eglfloats(self.camera_matrix.to_opengl())

        # Upload the camera matrix to OpenGLES
        opengles.glUniformMatrix4fv(self.camera_handle, 1, GL_FALSE, ccam)

        # Light must be transformed as well
        self._setLight()

    def _openWindow(self):
        """
        Open a window for the renderer.
        """
        if self.is_window_open:
            return
        
        self._openWindowPi()

        self.is_window_open = True

    def _openWindowPi(self):
        """
        Opens a (background) window on the Pi to be rendered to. 
        """

        # Get a OpenGL context from EGL. The OpenGL framebuffers are bound to this context
        self.ctx = EGL(depth_size = 8)

        # Define the shaders that draw the vertices. Camera and color are kept contant.
        vertex_shader = """
            uniform mat4 uCamera; 
            attribute vec4 aPosition;
            void main()
            {
                gl_Position = uCamera * aPosition;
            }
        """

        fragment_shader = """
            precision mediump float;
            uniform vec4 uColor;

            void main()
            {
                gl_FragColor = uColor;
            }
        """

        binding = ((5, 'aPosition'),)
        
        # Send the shaders to the context
        self.program = self.ctx.get_program(vertex_shader, fragment_shader, binding, False)
        self.logInfo("Program: %s" % self.program)

        # Get pointers to the shader parameters
        self.position_handle = opengles.glGetAttribLocation(self.program, "aPosition")
        self.logInfo("Position handle: %s" % self.position_handle)

        self.color_handle = opengles.glGetUniformLocation(self.program, "uColor")
        self.logInfo("Color handle: %s" % self.color_handle)

        self.camera_handle = opengles.glGetUniformLocation(self.program, "uCamera")
        self.logInfo("Camera handle: %s" % self.camera_handle)

        # Activate the program
        opengles.glUseProgram(self.program)
        self.logInfo("Use program: %s" % hex(opengles.glGetError()))

    def _clearAll(self):
        """
        Render a blank screen
        """
        opengles.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    def _renderDisplayList(self):
        """
        Empty the buffers and if a window is open, swap the buffers
        """
        # Update the window
        opengles.glFlush()
        opengles.glFinish()

        if self.show_window:
            openegl.eglSwapBuffers(self.ctx.display, self.ctx.surface)
        

    def _prepareDisplayList(self):
        """
        Does the main rendering of the bed and the part
        """

        # Define the vertices that make up the print bed. The vertices define two triangles that make up a square 
        # (squares are not directly supported in OpenGLES)
        self.logInfo("Load vertices")
        bedvertices = (   0, 0, 0,
                            0, self.bed_depth, 0,
                            self.bed_width, self.bed_depth, 0,
                            self.bed_width, self.bed_depth, 0,
                            self.bed_width, 0, 0,
                            0, 0, 0)
        cbedvertices = eglfloats(bedvertices)
        
        # Get the part vertices 
        # cvertices is a one-dimensional array: [x1a y1a z1a x1b y1b z1b x2a y2a ... ], where the number refers to the line number and a/b to start/end of the line.
        # Thus each line consists out of 6 floats
        N = len(self.base_vertices)
        cvertices = self.base_vertices
        self.logInfo("Vertices loaded")

        # Set the shader's color parameter to the part color 
        opengles.glUniform4f(self.color_handle, eglfloat(self.part_color[0]), eglfloat(self.part_color[1]), eglfloat(self.part_color[2]), eglfloat(1.0))
        self.logInfo("Coloring: %s" % hex(opengles.glGetError()))
        self.logInfo("Color: {0} {1} {2}".format(*self.part_color))

        # Enable VERTEX_ARRAY buffer
        opengles.glEnableClientState(GL_VERTEX_ARRAY)
        self.logInfo("Client state")

        # Create a Vertex Buffer Object
        vbo = eglint()
        opengles.glGenBuffers(1,ctypes.byref(vbo))
        self.logInfo("VBO: %s" % vbo.value)

        opengles.glBindBuffer(GL_ARRAY_BUFFER, vbo)
        self.logInfo("Bind buffer: %s" % hex(opengles.glGetError()))
        self.logInfo("N vertices: %s" % N)
        self.logInfo("Buffer size: %s" % ctypes.sizeof(cvertices))

        # Fill the buffer with the vertices
        # TODO: This loads the entire vertice buffer at once to the GPU mem. (May be 100s of mbs), may be try and load this sequentially in chuncks of x mb
        opengles.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(cvertices), ctypes.byref(cvertices), GL_STATIC_DRAW)
        self.logInfo("Buffer filled %s" % hex(opengles.glGetError()))

        # No need for these anymore, due to the use of a VBO
        #opengles.glEnableVertexAttribArray(self.position_handle)
        #self.logInfo("Enable part vertex: %s" % hex(opengles.glGetError()))

        opengles.glBindBuffer(GL_ARRAY_BUFFER, vbo)
        self.logInfo("Bind buffer: %s" % hex(opengles.glGetError()))

        # Now, load the VBO into the shader's position parameter
        opengles.glEnableVertexAttribArray(self.position_handle)
        opengles.glVertexAttribPointer(self.position_handle, 3, GL_FLOAT, GL_FALSE, 0, 0) # The array consists of 3 items per vertex (x, y, z)
        #opengles.glEnableVertexAttribArray(self.position_handle)
        self.logInfo("Set part vertex: %s" % hex(opengles.glGetError()))
        opengles.glBindBuffer(GL_ARRAY_BUFFER, vbo)

        # The position parameter is set, no start drawing. Because of GL_LINES, 2 vertices are expected per line = cvertices->a and b
        opengles.glDrawArrays( GL_LINES , 0, N/3 )
        self.logInfo("Draw part %s" % hex(opengles.glGetError()))

        # Remove the binding to the VBO
        opengles.glDisableVertexAttribArray(self.position_handle)
        self.logInfo("Disable vertex array %s" % hex(opengles.glGetError()))
        opengles.glBindBuffer(GL_ARRAY_BUFFER, 0)
        self.logInfo("Disable buffer %s" % hex(opengles.glGetError()))
        
        # Draw the bed in a similar way as the part, but without a VBO
        opengles.glUniform4f(self.color_handle, eglfloat(self.bed_color[0]), eglfloat(self.bed_color[1]), eglfloat(self.bed_color[2]), eglfloat(1.0))
        self.logInfo("Bed color %s" % hex(opengles.glGetError()))

        opengles.glVertexAttribPointer(self.position_handle, 3, GL_FLOAT, GL_FALSE, 0, cbedvertices) # 3 floats per vertex (x, y, z)
        self.logInfo("Bed vertex array %s" % hex(opengles.glGetError()))

        opengles.glEnableVertexAttribArray(self.position_handle)
        self.logInfo("Enable array %s" % hex(opengles.glGetError()))

        opengles.glDrawArrays ( GL_TRIANGLES, 0, 6 ) # 6 vertices make up two triangles, which make up 1 square
        self.logInfo("Draw bed array %s" % hex(opengles.glGetError()))

        opengles.glDisableVertexAttribArray(self.position_handle)
        self.logInfo("Disable array %s" % hex(opengles.glGetError()))

        opengles.glDeleteBuffers(1, ctypes.byref(vbo))
        self.logInfo("Delete buffer %s" % hex(opengles.glGetError()))

    def _updateCamera(self):
        """
        Sets the camera matrix to the given position
        """

        self.camera_matrix = Matrix44()

        # Lookat the center of the bed
        lookat = Matrix44.lookat((float(self.bed_width)/2, float(self.bed_depth)/2, 0), (0, 0, 1), (float(self.bed_width)/2, -100, 200))

        # Define the perspective of the camera
        projection = Matrix44.perspective_projection_fov(radians(90), float(self.width)/float(self.height), 0.1, 10000.0)

        # Calculate the camera matrix
        self.camera_matrix = projection * lookat

        # Upload the camera matrix to the shader
        ccam = eglfloats(self.camera_matrix.to_opengl())
        opengles.glUniformMatrix4fv(self.camera_handle, 1, GL_FALSE, ccam)

        # Light must be transformed as well
        self._setLight()

    
    def _setLight(self):
        #TODO: Experiment more with lighting. For now, it looks like materials are not supported for GL_LINES (makes sense)
        light_ambient =  0.0, 0.0, 0.0, 1.0 
        light_diffuse =  1.0, 1.0, 1.0, 1.0 
        light_specular =  1.0, 1.0, 1.0, 1.0 
        light_position = 1.0, 1.0, 1.0, 0.0 

        mat_specular = 1.0, 1.0, 1.0, 1.0 
        mat_shininess =  50.0 

    def _setViewportAndPerspective(self):
        """
        Sets the width and height of the viewport
        """
        opengles.glViewport(0, 0, self.width, self.height)
        self.logInfo("Set viewport %s" % hex(opengles.glGetError()))

    def _setLighting(self):
        """
        Sets the clear color and enables depth testing
        """
        opengles.glEnable(GL_DEPTH_TEST)
        self.logInfo("Enable depth test %s" % hex(opengles.glGetError()))
        opengles.glClearColor(eglfloat(1.), eglfloat(1.), eglfloat(1.), eglfloat(1.))
        self.logInfo("Set color %s" % hex(opengles.glGetError()))

    def _getVertices(self):
        """
        Gets the vertices that make up the gcode model
        """
        return self.gcode_model.segments

class RendererOpenGL(Renderer):
    def __init__(self, verbose = False):
        Renderer.__init__(self, verbose)
        self.show_window = False
        self.is_initialized = False
        self.is_window_open = False
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.bed_width = DEFAULT_BED_WIDTH
        self.bed_depth = DEFAULT_BED_DEPTH
        self.sync_offset = DEFAULT_SYNC_OFFSET
        self.background_color = DEFAULT_BACKGROUND_COLOR
        self.bed_color = DEFAULT_BED_COLOR
        self.part_color = DEFAULT_PART_COLOR
        self.camera_position = DEFAULT_CAMERA_POSITION
        self.camera_rotation = DEFAULT_CAMERA_ROTATION
        self.gcode_model = None
        self.base_vertices = None
        self.display_list = None
        self.rotation_direction = Vector3()
        self.rotation_speed = DEFAULT_CAMERA_ROTATION_SPEED
        self.movement_direction = Vector3()
        self.movement_speed = DEFAULT_CAMERA_MOVEMENT_SPEED
        self.camera_distance = DEFAULT_CAMERA_DISTANCE # Distance from object
        self.ctx = None
        self.program = None
                
    def initialize(self, bedWidth, bedDepth, width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT, showWindow = False,  backgroundColor = None, partColor = None, bedColor = None, cameraPosition = None, cameraRotation = None):
        if self.is_initialized:
            return

        self.bed_width = bedWidth
        self.bed_depth = bedDepth
        self.width = width
        self.height = height
        self.show_window = showWindow

        if backgroundColor:
            self.background_color = backgroundColor
          
        if bedColor:
            self.bed_color = bedColor

        if partColor:
            self.part_color = partColor
            
        if cameraPosition:
            self.camera_position = cameraPosition
        else:
            self.camera_position = (self.bed_width / 2, DEFAULT_CAMERA_POSITION[1], DEFAULT_CAMERA_POSITION[2]) # Move to x-center

        if cameraRotation:
            self.camera_rotation = cameraRotation

        self._openWindow()
        self._setViewportAndPerspective()
        self._setLighting()
        self._clearAll()
        self._updateCamera()

        self.is_initialized = True

    def close(self):
        if not self.is_initialized or not self.is_window_open:
            return
        
        sdl2.SDL_GL_DeleteContext(self.context)
        sdl2.SDL_DestroyWindow(self.window)
        sdl2.SDL_Quit()

    def renderModel(self, gcodeFile, bringCameraInPosition = False):
        if not self.is_initialized or not self.is_window_open:
            return

        # Parse the file
        self.logInfo("Parsing started")
        parser = GcodeParser(self.verbose)
        self.gcode_model = parser.parseFile(gcodeFile)
        self.logInfo("Parsing completed")
        if self.gcode_model.syncOffset > 0:
            self.sync_offset = self.gcode_model.syncOffset

        self.base_vertices = self._getVertices()
        self.logInfo("Rendering started")
        self._clearAll()
        self._setLight()
        self._prepareDisplayList()        

        if bringCameraInPosition:
            self._bringCameraInPosition()

        if self.show_window:
            while True:
                self._clearAll()
                self._setLight()
                self._renderDisplayList()
        else:
            self._initFrameBuffer()
            self._clearAll()
            self._setLight()
            self._renderDisplayList()
        self.logInfo("Rendering complete")


    def clear(self):
        if not self.is_initialized or not  self.is_window_open:
            return

        self._clearAll()
        self._renderBed()
    
    def save(self, imageFile):
        if not self.is_initialized or not self.is_window_open:
            return
      
        # Create Buffer
        N = self.width*self.height*4
        data = (ctypes.c_uint8*N)()

        # Read all pixel colors
        glReadPixels(0,0,self.width,self.height,GL_RGBA,GL_UNSIGNED_BYTE, ctypes.byref(data))
        
        # Write raw data to image file
        imgSize = (self.width, self.height)
        img = Image.frombytes('RGBA', imgSize, data)
        img.transpose(Image.FLIP_TOP_BOTTOM).save(imageFile)

    def _initFrameBuffer(self):
        self.fbo = ctypes.c_uint()
        self.color_buf = ctypes.c_uint()
        self.depth_buf = ctypes.c_uint()

        # Framebuffer
        glGenFramebuffers(1,self.fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        
        #Colorbuffer
        glGenRenderbuffers(1,self.color_buf)
        glBindRenderbuffer(GL_RENDERBUFFER, self.color_buf)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, self.width, self.height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, self.color_buf)

        #Depthbuffer
        glGenRenderbuffers(1, self.depth_buf)
        glBindRenderbuffer(GL_RENDERBUFFER, self.depth_buf)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, self.width, self.height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self.depth_buf)

    def _deinitFrameBuffer(self):
       glDeleteRenderbuffersEXT(1, self.color_buffer)
       glDeleteRenderbuffersEXT(1, self.depth_buffer)
       glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, 0)
       glDeleteFramebuffersEXT(1, self.fbo)

    def _bringCameraInPosition(self):

        if self.gcode_model.bbox:
            if self.gcode_model.printMode == 'sync':
                object_center = Vector3(self.gcode_model.bbox.cx() + self.sync_offset / 2, self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.gcode_model.bbox.xmax+self.sync_offset - self.gcode_model.bbox.xmin, self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
            elif self.gcode_model.printMode == 'mirror':
                object_center = Vector3(self.bed_width / 2, self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.bed_width - self.gcode_model.bbox.xmin*2, self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
            else:
                object_center = Vector3(self.gcode_model.bbox.cx(), self.gcode_model.bbox.cy(), self.gcode_model.bbox.cz())
                scale = max(self.gcode_model.bbox.dx(), self.gcode_model.bbox.dy(), self.gcode_model.bbox.dz())  / 75
        else:
            object_center = Vector3(self.bed_width/2, self.bed_depth/2, 0)
            scale = 1

        cam_dist = Vector3(self.camera_distance) * scale
        self.camera_position = (object_center + cam_dist).as_tuple()

        up = (0, 0, 1)

        glLoadIdentity()
        gluLookAt(self.camera_position[0], self.camera_position[1], self.camera_position[2],
                    object_center[0], object_center[1], object_center[2], 
                    up[0], up[1], up[2])

    def _openWindow(self):
        if self.is_window_open:
            return
               
        sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)

        self.window = sdl2.SDL_CreateWindow(b"OpenGL demo",

                                   sdl2.SDL_WINDOWPOS_UNDEFINED,

                                   sdl2.SDL_WINDOWPOS_UNDEFINED, self.width, self.height,

                                   sdl2.SDL_WINDOW_OPENGL|sdl2.SDL_WINDOW_HIDDEN)


        #if not self.show_window:
            #sdl2.Window.minimize()


        self.context = sdl2.SDL_GL_CreateContext(self.window)

        self.is_window_open = True

    def _clearAll(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    def _renderDisplayList(self):
        glCallList(self.display_list)
        
        # Update the window
        sdl2.SDL_GL_SwapWindow(self.window)
        

    def _prepareDisplayList(self):
        
        # Prepare batch
        self.display_list = glGenLists(1)    
        glNewList(self.display_list, GL_COMPILE)
    
        # Render all vertices
        glLineWidth(1)
        glColor( self.part_color )      
        glBegin(GL_LINES)
        for i in xrange(0, len(self.base_vertices), 3):
            glVertex((self.base_vertices[i], self.base_vertices[i+1], self.base_vertices[i+2]))     

        glEnd()
        
        #Render bed
        glColor( self.bed_color )       

        glBegin(GL_QUADS)
            
        glVertex(0, 0, 0)
        glVertex(0, self.bed_depth, 0)
        glVertex(self.bed_width, self.bed_depth, 0)
        glVertex(self.bed_width, 0, 0)

        glEnd()

        # Send batch
        glEndList()

    def _updateCamera(self):
        
        # Calculate camera matrix
        self.camera_matrix = Matrix44()
        self.camera_matrix.translate = self.camera_position
        self.rotation_matrix = Matrix44.xyz_rotation(*self.camera_rotation)
        self.camera_matrix *= self.rotation_matrix
        
        # Upload camera matrix
        glLoadMatrixd(self.camera_matrix.get_inverse().to_opengl())
        
        # Light must be transformed as well
        self._setLight()

    def _setLight(self):
        light_ambient =  0.0, 0.0, 0.0, 1.0 
        light_diffuse =  1.0, 1.0, 1.0, 1.0 
        light_specular =  1.0, 1.0, 1.0, 1.0 
        light_position = 1.0, 1.0, 1.0, 0.0 

        mat_specular = 1.0, 1.0, 1.0, 1.0 
        mat_shininess =  50.0 


        glLight(GL_LIGHT0, GL_AMBIENT, light_ambient);
        glLight(GL_LIGHT0, GL_DIFFUSE, light_diffuse);
        glLight(GL_LIGHT0, GL_SPECULAR, light_specular);
        glLight(GL_LIGHT0, GL_POSITION, light_position);

        glMaterial(GL_FRONT, GL_SPECULAR, mat_specular);
        glMaterial(GL_FRONT, GL_SHININESS, mat_shininess);

        glLight(GL_LIGHT0, GL_POSITION,  (0, 0, 1, 0))

    def _setViewportAndPerspective(self):
        # Set viewport
        glViewport(0, 0, self.width, self.height)

        # Set projection
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45.0, float(self.width)/self.height, 0.1, 1000.)

        # Reset mode, so camera may be adjusted
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def _setLighting(self):
        glEnable(GL_DEPTH_TEST)
        glShadeModel(GL_SMOOTH)

        glClearColor(1.0, 1.0, 1.0, 0.0)

        glEnable(GL_COLOR_MATERIAL)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_LINE_SMOOTH)

        glLight(GL_LIGHT0, GL_POSITION,  (0, 1, 1, 0))

    def _getVertices(self):
        return self.gcode_model.segments
