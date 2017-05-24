/*

Renderer.h

Header file with class definition for the main Gcode renderer. 

*/

#ifndef RENDERER_H
#define RENDERER_H 1

// Don't complain about fopen() and sprintf()
#define _CRT_SECURE_NO_WARNINGS
// We need PI
#define _USE_MATH_DEFINES
// libpng's setjmp gives compiler errors. We use exception handling without jumps anyways
#define PNG_SKIP_SETJMP_CHECK

// Include standard headers
#include <stdio.h>
#include <stdlib.h>
#include <algorithm>
#include <math.h>

// Include libpng
#include <png.h>

// OpenGL matrix and vector calc helpers
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include "helpers.h"
#include "glinit.h"
#include "shader.h"
#include "shaders.h"
#include "gcodeparser.h"

// Name container for an OpenGL vertex+element buffer
struct BufferInfo {
	GLuint indexBuffer, vertexBuffer, vertexArray;
	int nIndices, nVertices;
};

/* 
OpenGL / OpenGL ES gcode renderer

Relies on gcodeparser to provide vertex arrays. 
Saves PNG files using libpng.

*/
class Renderer
{
	
	int width = 250; // Width of image in pixels
	int height = 250; // Height of image in pixels

	RenderContextBase* renderContext;	// The platform-specific rendering context used as drawing buffer
	GcodeParser* parser;				// The gcode parser that provides the vertex arrays
	
	uint8_t drawType = DRAW_LINES;	// DRAW_LINES (fast) or DRAW_TUBES (slow, but cooler)
	uint16_t linesPerRun = 10000;	// Number of lines to parse before rendering

	BufferInfo bedBuffer;			// Name container for the bed vertex buffers
	long memoryUsed = 0;			// The amount of GPU memory used for drawing a part

	float * vertices;				// Points to the current vertex array
	short * indices;				// Points to the current vertex element array

	float bedWidth = 365.0f;		// Width (x) of the bed in mm
	float bedDepth = 350.0f;		// Depth (y) of the bed in mm
	float bedHeight = 200.0f;		// Height (z) of the build area in mm

	glm::vec2 bedOriginOffset = { 37.0f, 33.0f };								// 0,0 position in gcode space
	float partColor[4] = { 67.f / 255.f, 74.f / 255.f, 84.f / 255.f, 1.0f };	// Base color of the rendered part
	float bedColor[4] = { 0.75f, 0.75f, 0.75f, 1.0f };							// Base color of the rendered bed
	float backgroundColor[4] = { 1, 1, 1, 1 };									// Background color of the image 
	
	bool pointCameraAtPart = true;							// False: point camera at center of bed, true point camera at center of part
	glm::vec3 cameraDistance = { -300.f, -300.f, 150.f };	// Camera distance from the part or center of the bed			
		
	GLuint program, vertex_shader, fragment_shader, vertex_array;
	GLint position_handle,  // Position: the position of the vertices in model space
		normal_handle,		// Normals: The normals of fragments in model space
		color_handle,		// Color: the diffuse color of the fragments
		m_handle,			// The model matrix
		v_handle,			// The view matrix
		light_handle,		// Light: The position of the ambient light in the world space
		camera_handle;		// Camera: the full Model-View-Projection matrix of that transforms the vertice positions to pixel positions 

public:
	Renderer(int width, int height);
	~Renderer();
	void initialize();
	void renderGcode(const char* gcodeFile, const char* imageFile);

private:
	void checkGlError(const char* part);
	void draw(const float color[4], BufferInfo * bufferInfo, GLenum element_type);
	void buffer(const int nVertices, const float * vertices, const int nIndices, const short * indices, BufferInfo * bufferInfo);
	void deleteBuffer(BufferInfo * bufferInfo);
	void createProgram();
	void setCamera();
	void bufferBed();
	void renderBed();
	void renderPart();
	void saveRender(const char* imageFile);
};


#endif // !RENDERER_H



