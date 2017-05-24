#include "Renderer.h"

// Renderer constructor
// Width: width of the images to render
// Height: height of the images to render
Renderer::Renderer(int width, int height)
{
	this->width = width;
	this->height = height;

	this->renderContext = new T_RENDERCONTEXT(width, height);
}


Renderer::~Renderer()
{
	unloadShaders(this->program, this->vertex_shader, this->fragment_shader);

	delete[] vertices;
	delete[] indices;
	delete parser;
	delete renderContext;
}

// Check for any errors from the OpenGL API and log them
void Renderer::checkGlError(const char* part)
{
	GLenum error = glGetError();

	if (error != 0)
	{
		char desc[1024];
		sprintf(desc, "Error: %s %04x", part, error);
		log_msg(error, desc);
	}
}

// Initialize the render context and, if used, GLEW
void Renderer::initialize()
{
	log_msg(debug, "Initializing renderer");
	renderContext->activate();

#ifdef USE_GLEW
	if (glewInit() != GLEW_OK) {
		log_msg(error, "Failed to initialize GLEW");
		return;
	}
#endif

	// Load and compile shaders and get handles to the shader variables
	log_msg(debug, "Creating program");
	this->createProgram();

	// Before every rendering, clear the buffer with this background color
	glClearColor(backgroundColor[0], backgroundColor[1], backgroundColor[2], backgroundColor[3]);
	checkGlError("Set clear color");

	// For the tubes rendering mode, we need an ambient light position
	if (drawType == DRAW_TUBES)
	{
		glUniform3f(light_handle, bedWidth / 2, -50.0, 300.0);
		checkGlError("Set light");
	}

	// We can re-use the bed vertices, so load them once
	this->bufferBed();
	log_msg(debug, "Bed buffered");

}

// Render a gcode from a given gcodeFile in to a PNG imageFile
void Renderer::renderGcode(const char * gcodeFile, const char* imageFile)
{
	// The origin offset is not included, as it is not considered a valid printing area
	// and thus should not be rendered.
	BBox bedBbox = { 0, bedWidth, 0, bedDepth, 0, bedHeight };
	this->parser = new GcodeParser(gcodeFile, this->drawType, bedBbox);

	// Create buffers for the vertex and index arrays
	unsigned int verticesSize, indicesSize;

	this->parser->get_buffer_size(&verticesSize, &indicesSize);

	vertices = new float[this->linesPerRun * verticesSize];
	indices = new short[this->linesPerRun * indicesSize];

	// Start with a clean slate and fill the image with the background color
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

	// Render the part to the pixel buffer (and set the camera after the first run)
	this->renderPart();
	log_msg(debug, "Part rendered");

	// Render the bed to the pixel buffer
	this->renderBed();
	log_msg(debug, "Bed rendered");

	// Save the contents of the pixel buffer to a file
	this->saveRender(imageFile);
	log_msg(debug, "File saved");

	// Clean up
	delete[] vertices;
	delete[] indices;
	delete this->parser;
}

// Create a GPU shader program and create handles to the shader's variables
void Renderer::createProgram()
{
	// Compile the shaders
	if (drawType == DRAW_LINES)
		loadShaders(line_vertexshader, line_fragmentshader, &(this->program), &(this->vertex_shader), &(this->fragment_shader));
	else
		loadShaders(tube_vertexshader, tube_fragmentshader, &(this->program), &(this->vertex_shader), &(this->fragment_shader));

	// Get handles to the shader's variables
	position_handle = glGetAttribLocation(program, "vertexPosition_modelspace");
	checkGlError("Get position handle");

	color_handle = glGetUniformLocation(program, "ds_Color");
	checkGlError("Get color handle");

	camera_handle = glGetUniformLocation(program, "MVP");
	checkGlError("Get camera handle");

	// For the fragment shader that uses normals to create better lighting 
	// provide additional handles
	if (drawType == DRAW_TUBES)
	{
		light_handle = glGetUniformLocation(program, "LightPosition_worldspace");
		checkGlError("Get light handle");

		normal_handle = glGetAttribLocation(program, "vertexNormal_modelspace");
		checkGlError("Get normal handle");

		m_handle = glGetUniformLocation(program, "M");
		checkGlError("Get model-matrix handle");

		v_handle = glGetUniformLocation(program, "V");
		checkGlError("Get view-matrix handle");
	}

	// Enable the shader program
	glUseProgram(program);
	checkGlError("Use program");

	// Enable depth tests (this requires the context to have depth buffer)
	// prevents the bed from colliding with the part
	glEnable(GL_DEPTH_TEST);
	checkGlError("Enable depth test");
}

// Create a vertex buffer object using the given vertices 
// and indices of the vertices that make up the fragments (lines, triangles etc.)
void Renderer::buffer(const int nVertices, const float * vertices, const int nIndices, const short * indices, BufferInfo * bufferInfo)
{
	int vertexBuffer_size = nVertices * sizeof(float);
	int indexBuffer_size = nIndices * sizeof(short);

	GLuint vbo, ivbo, vertexArray;

#ifdef NEED_VERTEX_ARRAY_OBJECT

	glGenVertexArrays(1, &vertexArray);
	checkGlError("gen vertex array");

	glBindVertexArray(vertexArray);
	checkGlError("bind vertex array");
#endif

	// Create a buffer
	glGenBuffers(1, &vbo);
	checkGlError("generate vertex buffer");
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
	checkGlError("bind vertex buffer");

	// Load the vertices
	glBufferData(GL_ARRAY_BUFFER, vertexBuffer_size, vertices, GL_STATIC_DRAW);
	checkGlError("Vertex buffer data");

	// Create another buffer
	glGenBuffers(1, &ivbo);
	checkGlError("generate index buffer");
	glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ivbo);
	checkGlError("bind index buffer");

	// Load the indices
	glBufferData(GL_ELEMENT_ARRAY_BUFFER, indexBuffer_size, indices, GL_STATIC_DRAW);
	checkGlError("index buffer data");

	// Save links to the buffers in a bufferInfo struct
	(*bufferInfo).nVertices = nVertices;
	(*bufferInfo).nIndices = nIndices;
	(*bufferInfo).vertexBuffer = vbo;
	(*bufferInfo).indexBuffer = ivbo;
	(*bufferInfo).vertexArray = vertexArray;

	// Count how much data we're buffering
	memoryUsed += vertexBuffer_size + indexBuffer_size;
}

// Clear a buffer from the GPU memory
void Renderer::deleteBuffer(BufferInfo * bufferInfo)
{
	// Unwire
	glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
	checkGlError("Unbind element array buffer");

	glBindBuffer(GL_ARRAY_BUFFER, 0);
	checkGlError("Unbind vertex array buffer");

	// Delete buffers
	GLuint toDelete[] = { (*bufferInfo).vertexBuffer, (*bufferInfo).indexBuffer };
	glDeleteBuffers(2, toDelete);
	checkGlError("Delete buffers");

#ifdef NEED_VERTEX_ARRAY_OBJECT
	glBindVertexArray(0);
	checkGlError("Unbind vertex array");

	glDeleteVertexArrays(1, &(*bufferInfo).vertexArray);
	checkGlError("Delete vertex array");
#endif
}

// Draws a vertex buffer object to the render buffer
void Renderer::draw(const float color[4], BufferInfo * bufferInfo, GLenum element_type)
{
	// Set the base color of the fragments to be drawn
	glUniform4fv(color_handle, 1, color);
	checkGlError("Set color");

#ifdef NEED_VERTEX_ARRAY_OBJECT
	glBindVertexArray((*bufferInfo).vertexArray);
	checkGlError("bind vertex array");
#endif

	// Allow the shader's position variable to accept vertex buffers
	glEnableVertexAttribArray(position_handle);
	checkGlError("Enable vertex array position");

	if (drawType == DRAW_TUBES)
	{
		// Allow the shader's normals variable to accept vertex buffers
		glEnableVertexAttribArray(normal_handle);
		checkGlError("Enable vertex array normals");
	}

	// Bind to the vertex buffer
	glBindBuffer(GL_ARRAY_BUFFER, (*bufferInfo).vertexBuffer);
	checkGlError("Bind buffer");

	// Wire the vertex buffer to the position variable, and if needed, to the normals variable
	if (drawType == DRAW_TUBES)
	{	
		glVertexAttribPointer(position_handle, 3, GL_FLOAT, GL_FALSE, sizeof(float) * 6, (void*)0);
		checkGlError("Position pointer");

		glVertexAttribPointer(normal_handle, 3, GL_FLOAT, GL_FALSE, sizeof(float) * 6, (void*)(3 * sizeof(float)));
		checkGlError("Normal pointer");
	}
	else
	{
		glVertexAttribPointer(position_handle, 3, GL_FLOAT, GL_FALSE, sizeof(float) * 3, (void*)0);
		checkGlError("Position pointer");
	}

	// Bind to the vertex elements buffer (containing the indices of the vertices to draw) 
	glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, (*bufferInfo).indexBuffer);
	checkGlError("Bind elements");

	// Draw the vertices from the given indices
	// Note: OpenGL ES is limited to using shorts
	glDrawElements(element_type, (*bufferInfo).nIndices, GL_UNSIGNED_SHORT, (void*)0);
	checkGlError("Draw");

	// Unwire buffers
	glDisableVertexAttribArray(position_handle);
	checkGlError("Disable position array");

	if (drawType == DRAW_TUBES)
	{
		glDisableVertexAttribArray(normal_handle);
		checkGlError("Disable normal array");
	}
}

// Sets the camera 
void Renderer::setCamera()
{
	BBox bbox;

	glm::vec3 cameraPosition, cameraTarget;

	// Start with a field-of-view for the camera of 20 deg
	float fov_deg = 20.0f;
	
	if (parser->get_bbox(&bbox))
	{
		// Never go below this fov
		float fov_deg_min = 5.0f;

		if (this->pointCameraAtPart)
		{
			// Point to the middle of the part
			cameraTarget = glm::vec3((bbox.xmax + bbox.xmin) / 2, (bbox.ymax + bbox.ymin) / 2, (bbox.zmax + bbox.zmin) / 2);

			// TODO: Determine the FOV based on the bounding box and camera angle
			float part_width = bbox.xmax - bbox.xmin;
			float part_depth = bbox.ymax - bbox.ymin;

			// Range offset from 0.0 (empty part), to 1.0 (full bed used, widest angle needed)
			float x_factor = part_width / bedWidth;
			float y_factor = part_depth / bedDepth;

			// Use the biggest factor and scale to max 60 degrees (which is ~ the whole bed)
			float factor_max = max(x_factor, y_factor);
			fov_deg = max(fov_deg_min, factor_max * 60.0f);

		}
		else
		{
			// Point to the middle of the bed
			cameraTarget = glm::vec3((bedWidth - bedOriginOffset[0]) / 2, (bedDepth - bedOriginOffset[1]) / 2, 0);

			// Narrow or widen FOV

			// Minimal smallest offset to bed edges
			float x_offset_min = min(bedOriginOffset[0] + bbox.xmin, bedWidth - bedOriginOffset[0] - bbox.xmax);
			float y_offset_min = min(bedOriginOffset[1] + bbox.ymin, bedDepth - bedOriginOffset[1] - bbox.ymax);

			// Range offset from 0.0 (center of bed, smallest possible angle), to 1.0 (full bed used, widest angle needed)
			float x_factor = 1.0f - x_offset_min / (bedWidth / 2);
			float y_factor = 1.0f - y_offset_min / (bedDepth / 2);

			// Use the biggest factor and scale to max 60 degrees (which is ~ the whole bed)
			float factor_max = max(x_factor, y_factor);

			fov_deg = max(fov_deg_min, factor_max * 60.0f);
		}
	}
	else
	{
		// We don't have a valid bounding box of the part
		// Point to the middle of the bed
		cameraTarget = glm::vec3((bedWidth - bedOriginOffset[0]) / 2, (bedDepth - bedOriginOffset[1]) / 2, 0);
	}

	// Move the camera away from the target
	cameraPosition = cameraTarget + cameraDistance;

	// Define the matrices that transform vertices to pixels
	glm::mat4 mvp, projection, view, model;
	glm::vec3 up = glm::vec3(0, 0, 1); // +Z is pointing upwards
	model = glm::mat4(1.0f); // We don't need to transform the model
	view = glm::lookAt(cameraPosition, cameraTarget, up);
	projection = glm::perspective<float>(glm::radians(fov_deg), width / (float)height, 0.1f, 1000.0f);

	mvp = projection * view * model;

	// Upload the camera matrix to OpenGL(ES)
	glUniformMatrix4fv(camera_handle, 1, GL_FALSE, &mvp[0][0]);
	checkGlError("Set camera matrix");

	// Provide additional matrices for the fragment shader that uses lighting
	if (drawType == DRAW_TUBES)
	{
		glUniformMatrix4fv(m_handle, 1, GL_FALSE, &model[0][0]);
		checkGlError("Set model matrix");
		glUniformMatrix4fv(v_handle, 1, GL_FALSE, &view[0][0]);
		checkGlError("Set view matrix");
	}
}

// Create vertex buffer for the bed
void Renderer::bufferBed()
{
	int bedvertices_n;
	float * bedvertices;

	float x_min = -bedOriginOffset[0];
	float x_max = bedWidth-bedOriginOffset[0];
	float y_min = -bedOriginOffset[1];
	float y_max = bedDepth - bedOriginOffset[1];


	// X, y, z, nx, ny, nz
	if (drawType == DRAW_TUBES)
	{
		bedvertices_n = 24;
		bedvertices = new float[bedvertices_n] {
			x_min, y_min, 0, 0, 0, 1.0f,
			x_min, y_max, 0, 0, 0, 1.0f,
			x_max, y_max, 0, 0, 0, 1.0f,
			x_max, y_min, 0, 0, 0, 1.0f
		};
	}
	else
	{
		bedvertices_n = 12;
		bedvertices = new float[bedvertices_n] {
			x_min, y_min, 0,
			x_min, y_max, 0,
			x_max, y_max, 0,
			x_max, y_min, 0,
		};
	}

	const int bedindices_n = 6;
	short bedindices[bedindices_n] = { 0, 1, 2, 2, 3, 0 };

	buffer(bedvertices_n, bedvertices, bedindices_n, bedindices, &bedBuffer);

	delete[] bedvertices;
}

// (Buffer and) render the bed to the pixel buffer
void Renderer::renderBed()
{
	draw(bedColor, &bedBuffer, GL_TRIANGLES);
}

// Read the part vertices from the gcode and render it to the pixel buffer
void Renderer::renderPart()
{
	log_msg(debug, "Begin rendering part");

	// Reset the amount of memory we have used
	memoryUsed = 0;

	// Keep pointers to what we need to render
	int nVertices, nIndices;
	BufferInfo buff;

	// Extract vertices from the first n lines of gcode
	parser->get_vertices(linesPerRun, &nVertices, vertices, &nIndices, indices);
	
	// Store them in the GPU
	buffer(nVertices, vertices, nIndices, indices, &buff);

	// The bounding box of the first layer is sufficient for our needs (set the camera FOV)
	// so at this point (before we rendered anything) we can point the camera
	// in the right direction
	this->setCamera();

	// With the camera in place we can start drawing
	if (drawType == DRAW_LINES)
		draw(partColor, &buff, GL_LINES);
	else
		draw(partColor, &buff, GL_TRIANGLES);
	
	// Free some space
	deleteBuffer(&buff);

	// Continue to read, buffer and draw the rest of the gcode file
	while (parser->get_vertices(linesPerRun, &nVertices, vertices, &nIndices, indices))
	{
		buffer(nVertices, vertices, nIndices, indices, &buff);

		if (drawType == DRAW_LINES)
			draw(partColor, &buff, GL_LINES);
		else
			draw(partColor, &buff, GL_TRIANGLES);

		deleteBuffer(&buff);
	}

	// Log how much GPU memory we used to draw this part
	char resp[512];
	sprintf(resp, "Total data processed: %d kb", memoryUsed / 1000);
	log_msg(debug, resp);
}

// Reads the pixel buffer and encodes the data into a PNG file
void Renderer::saveRender(const char* imageFile)
{
	// Wait for all commands to complete before we read the buffer
	glFlush();
	glFinish();

	// Create a buffer for the pixel data
	const int n = 4 * width*height;
	uint8_t *imgData = new uint8_t[n];

	// Read the pixels from the buffer
	glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, imgData);
	checkGlError("glReadPixels");

	// PNG file & data pointers
	FILE *fp = NULL;
	png_structp png_ptr = NULL;
	png_infop info_ptr = NULL;

	// Open file for writing (binary mode)
	fp = fopen(imageFile, "wb");
	if (fp == NULL) {
		log_msg(error, "Could not open image file for writing");
		//goto finalise;
	}

	// Initialize write structure
	png_ptr = png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
	if (png_ptr == NULL) {
		log_msg(error, "Could not allocate PNG write struct");
		//goto finalise;
	}

	// Initialize info structure
	info_ptr = png_create_info_struct(png_ptr);
	if (info_ptr == NULL) {
		log_msg(error, "Could not allocate PNG info struct");
		//goto finalise;
	}

	//TODO: Error handling without setjmp (not thread-safe)

	png_init_io(png_ptr, fp);

	// Write header (8 bit colour depth)
	png_set_IHDR(png_ptr, info_ptr, width, height,
		8, PNG_COLOR_TYPE_RGBA, PNG_INTERLACE_NONE,
		PNG_COMPRESSION_TYPE_BASE, PNG_FILTER_TYPE_BASE);

	// Write image data row-by-row inversively (flip Y)
	png_bytepp rows = (png_bytepp)png_malloc(png_ptr, height * sizeof(png_bytep));
	for (int i = 0; i < height; ++i) {
		rows[i] = &imgData[(height - i - 1) * width * 4];
	}
	
	png_set_rows(png_ptr, info_ptr, rows);

	// Encode and write the PNG file
	png_write_png(png_ptr, info_ptr, PNG_TRANSFORM_IDENTITY, NULL);
	png_write_end(png_ptr, info_ptr);

	png_free(png_ptr, rows);

	// Clean up
	if (fp != NULL) fclose(fp);
	if (info_ptr != NULL) png_free_data(png_ptr, info_ptr, PNG_FREE_ALL, -1);
	if (png_ptr != NULL) png_destroy_write_struct(&png_ptr, (png_infopp)NULL);

	delete[] imgData;

	return;
}
