# Memory Webapp

The memory webapp provides a browser-based interface for viewing and navigating through the memory storage system. It allows for easy exploration of memory entries stored in markdown format.

## Features

- Browse the complete memory tree structure
- View individual memory entries with markdown rendering
- Navigate through directories/folders
- View metadata for memory entries
- Search for specific memory content
- Breadcrumb navigation for easy location tracking

## Usage

To launch the memory webapp, use the following command:

```bash
hdev view-memory
```

This will start a local web server (by default at http://127.0.0.1:5000) and open a web browser pointed to the memory browser interface.

### Command Options

- `--port`: Specify a custom port (default is 5000)
- `--host`: Specify a custom host (default is 127.0.0.1)

Example:
```bash
hdev view-memory --port 8080 --host 0.0.0.0
```

## Interface

### Home Page

The home page displays the root of your memory tree, showing all top-level directories and files. Click on any entry to navigate to that location.

### Memory Entry View

When viewing a specific memory entry, the content is rendered as HTML from markdown. If available, metadata for the entry (such as creation date, update date, and version) is displayed at the bottom of the page.

### Directory View

Directory views display all subdirectories and memory entries contained within that directory, allowing you to navigate deeper into the memory structure.

### Navigation

- Use the breadcrumb trail at the top of the page to see your current location and navigate upward
- The "Home" link in the navbar takes you back to the root view
- Use the search bar to find specific content across your memory storage

## Technical Details

The memory webapp is built using:

- Flask for the web server
- Python's markdown library for rendering markdown content
- Standard HTML/CSS for the user interface

The webapp accesses memory content through the same MemoryManager used by other memory tools, ensuring consistent access and manipulation of memory data.