"""Memory web browser implementation.

Provides a web interface for browsing and viewing memory content.
"""

import os
import webbrowser
from pathlib import Path
from typing import Optional

import markdown
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
)

from silica.developer.memory import MemoryManager


class MemoryWebApp:
    """Web application for browsing memory content."""

    def __init__(self, memory_manager: MemoryManager):
        """Initialize the web application with a memory manager.

        Args:
            memory_manager: The memory manager to use for accessing memory content
        """
        self.memory_manager = memory_manager
        self.app = Flask(__name__)
        self.setup_routes()

        # Create a templates directory if needed
        self.templates_dir = Path(__file__).parent / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self.static_dir = Path(__file__).parent / "static"
        self.static_dir.mkdir(exist_ok=True)

    def setup_routes(self):
        """Set up the routes for the web application."""

        @self.app.route("/static/<path:filename>")
        def static_files(filename):
            return send_from_directory(self.static_dir, filename)

        @self.app.route("/")
        def index():
            """Root route that displays the memory tree."""
            return self.render_memory_tree()

        @self.app.route("/view/<path:memory_path>")
        def view_memory(memory_path):
            """View a specific memory entry."""
            return self.render_memory_entry(memory_path)

        @self.app.route("/browse/<path:directory_path>")
        def browse_directory(directory_path):
            """Browse a specific directory in the memory tree."""
            return self.render_memory_directory(directory_path)

        @self.app.route("/search")
        def search():
            """Search for memory entries."""
            query = request.args.get("query", "")
            if not query:
                return redirect(url_for("index"))
            return self.render_search_results(query)

    def render_memory_tree(self, prefix: Optional[str] = None):
        """Render the memory tree starting from the given prefix.

        Args:
            prefix: Optional prefix path to start from

        Returns:
            Rendered HTML template with the memory tree
        """
        # Clean up the prefix if it has any double slashes
        if prefix:
            clean_prefix = prefix.replace("//", "/")
        else:
            clean_prefix = prefix

        tree_result = self.memory_manager.get_tree(
            Path(clean_prefix) if clean_prefix else None
        )

        if not tree_result["success"]:
            content_block = render_template("error.html", error=tree_result["error"])
            return render_template(
                "base.html", content_block=content_block, breadcrumbs=[], title="Error"
            )

        # Create breadcrumb navigation
        breadcrumbs = self._create_breadcrumbs(clean_prefix) if clean_prefix else []

        # Process the tree to add full paths to all nodes
        processed_tree = self._process_tree_paths(
            tree_result["items"], clean_prefix or ""
        )

        content_block = render_template(
            "tree.html", tree=processed_tree, current_path=clean_prefix or ""
        )

        return render_template(
            "base.html",
            content_block=content_block,
            breadcrumbs=breadcrumbs,
            title="Memory Browser",
        )

    def _process_tree_paths(self, tree, current_path=""):
        """Process the tree to add full paths to all node keys.

        This function modifies the tree structure to include the full path in each node key,
        which makes it easier to generate correct links in the template.

        Args:
            tree: The tree structure to process
            current_path: The current path prefix

        Returns:
            A new tree structure with modified keys that include the full path
        """
        result = {}

        for key, value in tree.items():
            if key == "...":
                # Special case for ellipsis nodes
                result[key] = value
                continue

            # Skip empty keys
            if not key:
                continue

            # Construct the full path for this node
            if current_path:
                full_path = f"{current_path}/{key}".replace("//", "/")
            else:
                full_path = key

            if isinstance(value, dict) and value:
                # This is a directory node with children, process its children recursively
                processed_children = self._process_tree_paths(value, full_path)

                # Create a new dict with path information
                node_info = {
                    "name": key,
                    "path": full_path,
                    "children": processed_children,
                    "is_file": False,
                }

                result[key] = node_info
            else:
                # This is a leaf node (file or empty directory)
                # Check if it's an actual file by looking for the .md file
                md_path = self.memory_manager.base_dir / (full_path + ".md")
                is_file = md_path.exists()

                result[key] = {"name": key, "path": full_path, "is_file": is_file}

        return result

    def render_memory_entry(self, memory_path: str):
        """Render a specific memory entry.

        Args:
            memory_path: Path to the memory entry to render

        Returns:
            Rendered HTML template with the memory entry content
        """
        full_path = self.memory_manager.base_dir / memory_path

        # Handle directory case
        if full_path.is_dir():
            return self.render_memory_directory(memory_path)

        # Get the memory entry content as structured data
        result = self.memory_manager.read_entry(memory_path)

        if not result["success"]:
            content_block = render_template("error.html", error=result["error"])
            return render_template(
                "base.html", content_block=content_block, breadcrumbs=[], title="Error"
            )

        # Create breadcrumb navigation
        breadcrumbs = self._create_breadcrumbs(memory_path)

        # Get data from the structured response
        content_text = result["content"] or ""
        metadata = result["metadata"] or {}

        # Convert markdown to HTML
        content_html = markdown.markdown(content_text)

        content_block = render_template(
            "entry.html",
            content=content_html,
            metadata=metadata,
            memory_path=memory_path,
        )

        return render_template(
            "base.html",
            content_block=content_block,
            breadcrumbs=breadcrumbs,
            title=f"Memory: {memory_path}",
        )

    def render_memory_directory(self, directory_path: str):
        """Render the contents of a memory directory.

        Args:
            directory_path: Path to the directory to render

        Returns:
            Rendered HTML template with the directory contents
        """
        try:
            # Get directory content using the memory manager
            result = self.memory_manager.read_entry(directory_path)

            if not result["success"]:
                content_block = render_template("error.html", error=result["error"])
                return render_template(
                    "base.html",
                    content_block=content_block,
                    breadcrumbs=[],
                    title="Error",
                )

            if result["type"] != "directory":
                content_block = render_template(
                    "error.html", error=f"Expected directory, found {result['type']}"
                )
                return render_template(
                    "base.html",
                    content_block=content_block,
                    breadcrumbs=[],
                    title="Error",
                )

            # Get the items directly from the structured data
            items = []
            for item in result["items"]:
                path = item["path"]

                # Make sure we have clean path with proper structure
                if directory_path and not path.startswith(directory_path):
                    if directory_path.endswith("/"):
                        full_path = directory_path + path
                    else:
                        full_path = f"{directory_path}/{path}"
                    # Clean up any double slashes
                    full_path = full_path.replace("//", "/")
                else:
                    full_path = path

                items.append(
                    {
                        "name": Path(path).name,
                        "path": full_path,
                        "is_directory": item["type"] == "node",
                    }
                )

            # Create breadcrumb navigation
            breadcrumbs = self._create_breadcrumbs(directory_path)

            content_block = render_template(
                "directory.html", items=items, directory_path=directory_path
            )

            return render_template(
                "base.html",
                content_block=content_block,
                breadcrumbs=breadcrumbs,
                title=f"Directory: {directory_path}",
            )
        except Exception as e:
            content_block = render_template("error.html", error=str(e))

            return render_template(
                "base.html", content_block=content_block, breadcrumbs=[], title="Error"
            )

    def render_search_results(self, query: str):
        """Render the results of a memory search.

        Args:
            query: Search query

        Returns:
            Rendered HTML template with the search results
        """
        # We need to implement a basic search functionality using Python
        # This is a simple implementation that searches through all .md files

        results = []
        try:
            # Look for files containing the query
            for md_file in self.memory_manager.base_dir.glob("**/*.md"):
                # Skip metadata files
                if md_file.name.endswith(".metadata.json"):
                    continue

                # Get the relative path for the memory entry
                rel_path = md_file.relative_to(self.memory_manager.base_dir)
                memory_path = str(rel_path.with_suffix(""))

                # Read file content
                with open(md_file, "r") as f:
                    content = f.read()

                # Check if query is in content (case-insensitive)
                if query.lower() in content.lower():
                    # Extract a snippet of context around the match
                    idx = content.lower().find(query.lower())
                    start = max(0, idx - 50)
                    end = min(len(content), idx + len(query) + 50)

                    # Create a snippet with ellipsis if needed
                    snippet = ""
                    if start > 0:
                        snippet += "..."
                    snippet += content[start:end]
                    if end < len(content):
                        snippet += "..."

                    # Highlight the query in the snippet (case-insensitive)
                    import re

                    pattern = re.compile(re.escape(query), re.IGNORECASE)
                    highlighted_snippet = pattern.sub(
                        lambda m: f"<mark>{m.group(0)}</mark>", snippet
                    )

                    # Add to results
                    results.append(
                        {"path": memory_path, "snippet": highlighted_snippet}
                    )
        except Exception as e:
            # If there's an error, we'll show it in the results
            results.append(
                {"path": "Error", "snippet": f"Error during search: {str(e)}"}
            )

        content_block = render_template("search.html", query=query, results=results)

        return render_template(
            "base.html",
            content_block=content_block,
            breadcrumbs=[],
            title=f"Search: {query}",
        )

    def _create_breadcrumbs(self, path: str):
        """Create breadcrumb navigation for a path.

        Args:
            path: Path to create breadcrumbs for

        Returns:
            List of breadcrumb items with name and path
        """
        if not path:
            return []

        parts = Path(path).parts
        breadcrumbs = [{"name": "Home", "path": "/"}]

        current_path = ""
        for i, part in enumerate(parts):
            # Properly join path parts using Path object
            if current_path:
                current_path = str(Path(current_path) / part)
            else:
                current_path = part

            # Determine if this is a directory or file
            is_last = i == len(parts) - 1
            full_path = self.memory_manager.base_dir / current_path

            # Check if it's a directory
            is_dir = full_path.is_dir()

            # If it's not a directory, it might be a memory entry (without extension)
            if not is_dir:
                # Check if the .md file exists
                md_path = full_path.with_suffix(".md")
                is_file = md_path.exists()
            else:
                is_file = False

            # Create clean URLs without duplicate slashes
            url = f"/browse/{current_path}" if is_dir else f"/view/{current_path}"
            if is_last and is_file:
                url = f"/view/{current_path}"

            # Replace any accidental double slashes
            url = url.replace("//", "/")

            breadcrumbs.append({"name": part, "path": url})

        return breadcrumbs

    def run(self, host: str = "127.0.0.1", port: int = 5500, open_browser: bool = True):
        """Run the web application.

        Args:
            host: Hostname to bind to
            port: Port to bind to
            open_browser: Whether to open a browser window automatically
        """
        if open_browser:
            webbrowser.open(f"http://{host}:{port}")
        self.app.run(host=host, port=port)


def run_memory_webapp(
    memory_dir: Optional[Path] = None, host: str = "127.0.0.1", port: int | None = None
):
    """Run the memory webapp.

    Args:
        memory_dir: Optional path to the memory directory to use
        host: Hostname to bind to
        port: Port to bind to
    """
    if not port:
        try:
            port = int(os.getenv("PORT", 8000))
        except ValueError:
            port = 5500
    memory_manager = MemoryManager(memory_dir)
    app = MemoryWebApp(memory_manager)

    print(f"Starting memory browser at http://{host}:{port}")
    print("Press Ctrl+C to stop the server")

    app.run(host=host, port=port)
