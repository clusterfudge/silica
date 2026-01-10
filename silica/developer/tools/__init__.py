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

# Gmail and Calendar tools have been migrated to user tools
# See ~/.silica/tools/gmail.py and ~/.silica/tools/gcal.py
# The user tools take precedence over built-in tools with the same name
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

from .user_choice import (
    user_choice,
)
from .toolbox_tools import (
    toolbox_list,
    toolbox_create,
    toolbox_inspect,
    toolbox_shelve,
    toolbox_test,
)
from .planning import (
    enter_plan_mode,
    ask_clarifications,
    update_plan,
    add_plan_tasks,
    read_plan,
    list_plans,
    exit_plan_mode,
    complete_plan_task,
    complete_plan,
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
        # Shell tools (dual architecture)
        shell_execute,
        shell_session_create,
        shell_session_execute,
        shell_session_list,
        shell_session_get_output,
        shell_session_destroy,
        shell_session_set_timeout,
        # Gmail and Calendar tools removed - now provided by user tools
        # See ~/.silica/tools/gmail.py and ~/.silica/tools/gcal.py
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
        user_choice,
        # Toolbox tools for managing user-created tools
        toolbox_list,
        toolbox_create,
        toolbox_inspect,
        toolbox_shelve,
        toolbox_test,
        # Planning tools
        enter_plan_mode,
        ask_clarifications,
        update_plan,
        add_plan_tasks,
        read_plan,
        list_plans,
        exit_plan_mode,
        complete_plan_task,
        complete_plan,
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
