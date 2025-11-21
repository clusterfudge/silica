from .subagent import agent
from .files import read_file, write_file, list_directory, edit_file
from .sandbox_debug import sandbox_debug
from .repl import python_repl
from .shell import (
    shell_execute,
    shell_session_create,
    shell_session_execute,
    shell_session_list,
    shell_session_get_output,
    shell_session_destroy,
    shell_session_set_timeout,
)
from .web import web_search, safe_curl
from .browser_session_tools import (
    get_browser_capabilities,
    browser_session_create,
    browser_session_navigate,
    browser_session_interact,
    browser_session_inspect,
    browser_session_screenshot,
    browser_session_list,
    browser_session_destroy,
    browser_session_get_info,
)
from .gcal import (
    calendar_setup,
    calendar_list_events,
    calendar_create_event,
    calendar_delete_event,
    calendar_search,
    calendar_list_calendars,
)
from .gmail import (
    gmail_search,
    gmail_read,
    gmail_send,
    gmail_read_thread,
    find_emails_needing_response,
    gmail_forward,
)
from .memory import (
    get_memory_tree,
    search_memory,
    read_memory_entry,
    write_memory_entry,
    critique_memory,
    delete_memory_entry,
)
from .todos import (
    todo_read,
    todo_write,
)
from .sessions import (
    list_sessions_tool,
    get_session_tool,
)
from .github import GITHUB_TOOLS
from .github_comments import (
    GITHUB_COMMENT_TOOLS,
)
from .persona_tools import (
    read_persona,
    write_persona,
)
from .webcam import (
    get_webcam_capabilities,
    webcam_snapshot,
)
from ..knowledge_graph.tools import (
    # parse_annotations and save_annotations are deprecated - annotations are now
    # automatically extracted in the agent loop
    query_knowledge_graph,
    get_kg_statistics,
    get_recent_topics,
    query_by_date,
)

ALL_TOOLS = (
    [
        read_file,
        write_file,
        list_directory,
        edit_file,
        sandbox_debug,
        web_search,
        agent,
        safe_curl,
        python_repl,
        # Browser tools
        get_browser_capabilities,
        # Browser session tools
        browser_session_create,
        browser_session_navigate,
        browser_session_interact,
        browser_session_inspect,
        browser_session_screenshot,
        browser_session_list,
        browser_session_destroy,
        browser_session_get_info,
        # Webcam tools
        get_webcam_capabilities,
        webcam_snapshot,
        # Shell tools (dual architecture)
        shell_execute,
        shell_session_create,
        shell_session_execute,
        shell_session_list,
        shell_session_get_output,
        shell_session_destroy,
        shell_session_set_timeout,
        gmail_search,
        gmail_read,
        gmail_send,
        gmail_read_thread,
        find_emails_needing_response,
        gmail_forward,
        calendar_list_events,
        calendar_create_event,
        calendar_delete_event,
        calendar_search,
        calendar_setup,
        calendar_list_calendars,
        get_memory_tree,
        search_memory,
        read_memory_entry,
        write_memory_entry,
        critique_memory,
        delete_memory_entry,
        todo_read,
        todo_write,
        list_sessions_tool,
        get_session_tool,
        read_persona,
        write_persona,
        # Knowledge graph tools (parse/save are automatic now)
        query_knowledge_graph,
        get_kg_statistics,
        get_recent_topics,
        query_by_date,
    ]
    + GITHUB_TOOLS
    + GITHUB_COMMENT_TOOLS
)


try:
    from heare.developer.clients.plane_so import get_project_from_config
    from heare.developer.tools.issues import PLANE_TOOLS

    project = get_project_from_config()
    if project:
        ALL_TOOLS += PLANE_TOOLS
except Exception:
    pass

# try:
#     from ..personas import basic_agent, coding_agent, deep_research_agent
#
#     ALL_TOOLS += [basic_agent, coding_agent, deep_research_agent]
# except Exception as e:
#     print(f"Error importing personas: {repr(e)}")
