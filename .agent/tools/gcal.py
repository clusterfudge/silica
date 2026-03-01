#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "cyclopts",
#     "google-api-python-client",
#     "google-auth-oauthlib",
#     "google-auth-httplib2",
#     "pytz",
#     "pyyaml",
# ]
# ///

"""Google Calendar tools for managing events and calendars.

Provides calendar access through the Google Calendar API with OAuth authentication.
Supports listing, creating, deleting, and searching events across multiple calendars.

Metadata:
    category: productivity
    tags: calendar, gcal, google, events, scheduling
    creator_persona: system
    created: 2025-01-13
    long_running: false
    requires_auth: true
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cyclopts
import pytz
import yaml
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema, generate_schemas_for_commands
from _google_auth import get_credentials, check_credentials, get_config_dir, ensure_config_dir

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

app = cyclopts.App()


def _get_config_path() -> Path:
    """Get path to calendar configuration file."""
    return get_config_dir() / "google-calendar.yml"


def _get_service():
    """Get authenticated Calendar API service."""
    creds = get_credentials(CALENDAR_SCOPES, "calendar_token.pickle")
    return build("calendar", "v3", credentials=creds)


def _get_user_timezone(service, calendar_id="primary") -> str:
    """Get the user's calendar timezone."""
    try:
        calendar_info = service.calendars().get(calendarId=calendar_id).execute()
        return calendar_info.get("timeZone", "UTC")
    except Exception:
        return "UTC"


def _get_calendar_config() -> dict | None:
    """Load calendar configuration."""
    config_path = _get_config_path()
    if not config_path.exists():
        return None
    with open(config_path) as f:
        return yaml.safe_load(f)


def _save_calendar_config(config: dict) -> None:
    """Save calendar configuration."""
    ensure_config_dir()
    config_path = _get_config_path()
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def _get_enabled_calendars() -> list | None:
    """Get list of enabled calendars from config."""
    config = _get_calendar_config()
    if not config:
        return None
    return [cal for cal in config.get("calendars", []) if cal.get("enabled", True)]


def _list_available_calendars(service) -> list:
    """List all available calendars."""
    calendar_list = service.calendarList().list().execute()
    calendars = []
    for entry in calendar_list.get("items", []):
        calendars.append({
            "id": entry["id"],
            "summary": entry.get("summary", "Unnamed Calendar"),
            "description": entry.get("description", ""),
            "primary": entry.get("primary", False),
            "access_role": entry.get("accessRole", ""),
        })
    return calendars


def _format_event(event: dict, user_timezone: str, calendar_name: str = "Unknown") -> str:
    """Format a calendar event for display."""
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))

    # Format time
    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        local_tz = pytz.timezone(user_timezone)
        start_local = start_dt.astimezone(local_tz)
        end_local = end_dt.astimezone(local_tz)
        time_str = f"{start_local.strftime('%H:%M')} to {end_local.strftime('%H:%M')} ({user_timezone})"
        event_date = start_local.strftime("%Y-%m-%d")
    else:
        time_str = "(all day)"
        event_date = start.split("T")[0] if "T" in start else start

    def _make_busy(e):
        return f"Busy ({calendar_name})"

    event_text = (
        f"Event: {event.get('summary', _make_busy(event))}\n"
        f"Calendar: {calendar_name}\n"
        f"Date: {event_date}\n"
        f"Time: {time_str}\n"
        f"Creator: {event.get('creator', {}).get('displayName', 'Unknown')}\n"
    )

    if "location" in event:
        event_text += f"Location: {event['location']}\n"

    if "description" in event and event["description"].strip():
        description = event["description"]
        if len(description) > 200:
            description = description[:197] + "..."
        event_text += f"Description: {description}\n"

    if "attendees" in event:
        attendees = [a.get("email", "Unknown") for a in event["attendees"]]
        event_text += f"Attendees: {', '.join(attendees)}\n"

    event_text += f"ID: {event['id']}\n"
    return event_text, event_date


@app.command()
def list_events(
    days: int = 7,
    calendar_id: str = "",
    start_date: str = "",
    end_date: str = "",
    *,
    toolspec: bool = False,
):
    """List upcoming events from Google Calendar for specific dates.

    For queries about a specific day (like "tomorrow" or "next Monday"):
    - Convert relative date references to specific YYYY-MM-DD format dates
    - Use both start_date AND end_date parameters set to the SAME date
    - Always verify events are on the requested date before including them in your response

    Example usage:
    - For "tomorrow": Use start_date="2025-04-02", end_date="2025-04-02"
    - For "next week": Use days=7 (without start_date/end_date)
    - For a date range: Use both start_date and end_date with different dates

    Args:
        days: Number of days to look ahead (default: 7)
        calendar_id: ID of the calendar to query (default: None, which uses all enabled calendars)
        start_date: Optional start date in YYYY-MM-DD format (overrides days parameter)
        end_date: Optional end date in YYYY-MM-DD format (required if start_date is provided)
    """
    if toolspec:
        print(json.dumps(generate_schema(list_events, "calendar_list_events")))
        return

    try:
        config = _get_calendar_config()
        if not config and not calendar_id:
            print("No calendar configuration found. Please run calendar setup first, or specify a calendar_id.")
            return

        service = _get_service()
        user_timezone = _get_user_timezone(service, calendar_id if calendar_id else "primary")
        local_tz = pytz.timezone(user_timezone)

        # Calculate time range
        if start_date and end_date:
            try:
                start_time = local_tz.localize(datetime.strptime(start_date, "%Y-%m-%d"))
                end_time = local_tz.localize(
                    datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                )
                start_time = start_time.astimezone(pytz.UTC)
                end_time = end_time.astimezone(pytz.UTC)
                date_range_description = f"from {start_date} to {end_date}"
            except ValueError:
                print("Invalid date format. Please use YYYY-MM-DD format for dates.")
                return
        else:
            now = datetime.now(local_tz)
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=days)
            start_time = start_time.astimezone(pytz.UTC)
            end_time = end_time.astimezone(pytz.UTC)
            date_range_description = f"in the next {days} days"

        # Determine calendars to query
        calendars_to_query = []
        if calendar_id:
            calendars_to_query.append({"id": calendar_id, "name": "Specified Calendar"})
        else:
            enabled_calendars = _get_enabled_calendars()
            if not enabled_calendars:
                print("No enabled calendars found in configuration. Please run calendar setup first.")
                return
            calendars_to_query = enabled_calendars

        # Get events
        all_events = []
        start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        for cal in calendars_to_query:
            events_result = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=start_time_str,
                    timeMax=end_time_str,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            for event in events_result.get("items", []):
                event["calendar_name"] = cal.get("name", "Unknown Calendar")
                all_events.append(event)

        # Sort by start time
        all_events.sort(key=lambda x: x["start"].get("dateTime", x["start"].get("date")))

        if not all_events:
            print(f"No events found {date_range_description}.")
            return

        # Group by date
        events_by_date = {}
        for event in all_events:
            event_text, event_date = _format_event(event, user_timezone, event["calendar_name"])
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event_text)

        # Format output
        formatted_output = []
        for date in sorted(events_by_date.keys()):
            formatted_output.append(f"Events for {date}:")
            formatted_output.append("\n---\n".join(events_by_date[date]))

        print(f"Upcoming events {date_range_description}:\n\n" + "\n\n".join(formatted_output))

    except Exception as e:
        print(f"Error listing calendar events: {str(e)}")


@app.command()
def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
    calendar_id: str = "",
    *,
    toolspec: bool = False,
):
    """Create a new event in Google Calendar.

    Args:
        summary: Title/summary of the event
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS) or date (YYYY-MM-DD) for all-day events
        end_time: End time in ISO format (YYYY-MM-DDTHH:MM:SS) or date (YYYY-MM-DD) for all-day events
        description: Description of the event (optional)
        location: Location of the event (optional)
        attendees: Comma-separated list of email addresses to invite (optional)
        calendar_id: ID of the calendar to add the event to (default: None, which uses primary calendar)
    """
    if toolspec:
        print(json.dumps(generate_schema(create_event, "calendar_create_event")))
        return

    try:
        # Determine calendar
        if not calendar_id:
            config = _get_calendar_config()
            if config:
                calendars = config.get("calendars", [])
                primary_calendars = [
                    cal for cal in calendars
                    if cal.get("primary", False) and cal.get("enabled", True)
                ]
                if primary_calendars:
                    calendar_id = primary_calendars[0]["id"]
                else:
                    calendar_id = "primary"
            else:
                calendar_id = "primary"

        service = _get_service()

        # Check if all-day event
        is_all_day = "T" not in start_time

        event = {
            "summary": summary,
            "description": description,
            "location": location,
        }

        if is_all_day:
            event["start"] = {"date": start_time.split("T")[0] if "T" in start_time else start_time}
            event["end"] = {"date": end_time.split("T")[0] if "T" in end_time else end_time}
        else:
            # Get timezone
            try:
                calendar_info = service.calendars().get(calendarId=calendar_id).execute()
                user_timezone = calendar_info.get("timeZone", "UTC")
            except Exception:
                user_timezone = "UTC"

            local_tz = pytz.timezone(user_timezone)

            def _has_timezone(dt_str):
                if dt_str.endswith("Z"):
                    return True
                time_part_pos = dt_str.find("T")
                if time_part_pos == -1:
                    return False
                time_part = dt_str[time_part_pos + 1:]
                if ":" not in time_part:
                    return False
                for pos in range(time_part_pos + 8, len(dt_str)):
                    if dt_str[pos] in ("+", "-"):
                        return True
                return False

            # Handle start time
            if _has_timezone(start_time):
                event["start"] = {"dateTime": start_time}
            else:
                if "T" in start_time:
                    local_dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")
                    aware_dt = local_tz.localize(local_dt)
                    event["start"] = {"dateTime": aware_dt.isoformat()}
                else:
                    event["start"] = {"dateTime": start_time, "timeZone": user_timezone}

            # Handle end time
            if _has_timezone(end_time):
                event["end"] = {"dateTime": end_time}
            else:
                if "T" in end_time:
                    local_dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S")
                    aware_dt = local_tz.localize(local_dt)
                    event["end"] = {"dateTime": aware_dt.isoformat()}
                else:
                    event["end"] = {"dateTime": end_time, "timeZone": user_timezone}

        # Add attendees
        if attendees:
            event["attendees"] = [{"email": email.strip()} for email in attendees.split(",")]

        # Create event
        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()

        # Get calendar name
        try:
            calendar_info = service.calendars().get(calendarId=calendar_id).execute()
            calendar_name = calendar_info.get("summary", calendar_id)
        except Exception:
            calendar_name = calendar_id

        print(
            f"Event created successfully in calendar '{calendar_name}'.\n"
            f"Event ID: {created_event['id']}\n"
            f"Title: {summary}\n"
            f"Time: {start_time} to {end_time}"
        )

    except Exception as e:
        print(f"Error creating calendar event: {str(e)}")


@app.command()
def delete_event(
    event_id: str,
    calendar_id: str = "",
    *,
    toolspec: bool = False,
):
    """Delete an event from Google Calendar.

    Args:
        event_id: ID of the event to delete
        calendar_id: ID of the calendar containing the event (default: None, requiring confirmation)
    """
    if toolspec:
        print(json.dumps(generate_schema(delete_event, "calendar_delete_event")))
        return

    try:
        service = _get_service()

        # Find calendar if not specified
        if not calendar_id:
            enabled_calendars = _get_enabled_calendars()
            if not enabled_calendars:
                print("No calendar configuration found. Please provide the calendar_id.")
                return

            event_found = False
            event_summary = "Unknown Event"

            for cal in enabled_calendars:
                try:
                    event = service.events().get(calendarId=cal["id"], eventId=event_id).execute()
                    calendar_id = cal["id"]
                    event_found = True
                    event_summary = event.get("summary", "Unknown Event")
                    break
                except Exception:
                    continue

            if not event_found:
                print(f"Event {event_id} not found in any of your configured calendars.")
                return

            print(f"Found event '{event_summary}' in calendar '{cal.get('name', calendar_id)}'")
            print("Are you sure you want to delete this event? (y/n)")
            response = input("> ").strip().lower()
            if response != "y":
                print("Event deletion cancelled.")
                return

        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Event {event_id} deleted successfully.")

    except Exception as e:
        print(f"Error deleting calendar event: {str(e)}")


@app.command()
def search_events(
    query: str,
    days: int = 90,
    calendar_id: str = "",
    *,
    toolspec: bool = False,
):
    """Search for events in Google Calendar by keyword.

    This tool allows you to search for calendar events containing specific keywords
    in their title, description, or location.

    Args:
        query: The search term to look for in events
        days: Number of days to look ahead (default: 90)
        calendar_id: ID of the calendar to search (default: None, which searches all enabled calendars)
    """
    if toolspec:
        print(json.dumps(generate_schema(search_events, "calendar_search")))
        return

    try:
        config = _get_calendar_config()
        if not config and not calendar_id:
            print("No calendar configuration found. Please run calendar setup first, or specify a calendar_id.")
            return

        service = _get_service()
        user_timezone = _get_user_timezone(service, calendar_id if calendar_id else "primary")
        local_tz = pytz.timezone(user_timezone)

        now = datetime.now(local_tz)
        start_time = now - timedelta(days=days)
        end_time = now + timedelta(days=days)

        start_time = start_time.astimezone(pytz.UTC)
        end_time = end_time.astimezone(pytz.UTC)

        # Determine calendars
        calendars_to_query = []
        if calendar_id:
            calendars_to_query.append({"id": calendar_id, "name": "Specified Calendar"})
        else:
            enabled_calendars = _get_enabled_calendars()
            if not enabled_calendars:
                print("No enabled calendars found in configuration. Please run calendar setup first.")
                return
            calendars_to_query = enabled_calendars

        # Get events
        all_events = []
        start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        for cal in calendars_to_query:
            events_result = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=start_time_str,
                    timeMax=end_time_str,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            for event in events_result.get("items", []):
                event["calendar_name"] = cal.get("name", "Unknown Calendar")
                all_events.append(event)

        # Filter by query
        query_lower = query.lower()
        matching_events = []

        for event in all_events:
            if query_lower in event.get("summary", "").lower():
                matching_events.append(event)
                continue
            if query_lower in event.get("description", "").lower():
                matching_events.append(event)
                continue
            if query_lower in event.get("location", "").lower():
                matching_events.append(event)
                continue
            if "attendees" in event:
                for attendee in event["attendees"]:
                    if (query_lower in attendee.get("email", "").lower() or
                        query_lower in attendee.get("displayName", "").lower()):
                        matching_events.append(event)
                        break

        matching_events.sort(key=lambda x: x["start"].get("dateTime", x["start"].get("date")))

        if not matching_events:
            print(f"No events found matching '{query}' in the next {days} days.")
            return

        # Group by date
        events_by_date = {}
        for event in matching_events:
            event_text, event_date = _format_event(event, user_timezone, event["calendar_name"])
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event_text)

        # Format output
        formatted_output = []
        for date in sorted(events_by_date.keys()):
            formatted_output.append(f"Events for {date} matching '{query}':")
            formatted_output.append("\n---\n".join(events_by_date[date]))

        print(
            f"Found {len(matching_events)} events matching '{query}' in the next {days} days:\n\n"
            + "\n\n".join(formatted_output)
        )

    except Exception as e:
        print(f"Error searching calendar events: {str(e)}")


@app.command()
def setup(
    *,
    toolspec: bool = False,
):
    """Set up Google Calendar configuration by listing and selecting which calendars to enable.

    This tool guides the user through an interactive setup process to configure which
    Google Calendars should be visible and usable through the calendar tools.
    """
    if toolspec:
        print(json.dumps(generate_schema(setup, "calendar_setup")))
        return

    try:
        existing_config = _get_calendar_config()
        if existing_config:
            calendars = existing_config.get("calendars", [])
            enabled_calendars = [cal for cal in calendars if cal.get("enabled", False)]

            print(f"Calendar configuration already exists with {len(enabled_calendars)} enabled calendars.")
            print("Do you want to reconfigure? (y/n)")
            response = input("> ").strip().lower()
            if response != "y":
                print("Keeping existing calendar configuration.")
                return

        print("Fetching available calendars from Google...")
        service = _get_service()
        calendars = _list_available_calendars(service)

        if not calendars:
            print("No calendars found in your Google account.")
            return

        # Display calendars
        calendar_list = "Available calendars:\n\n"
        for i, cal in enumerate(calendars, 1):
            primary_indicator = " (primary)" if cal.get("primary", False) else ""
            calendar_list += f"{i}. {cal['summary']}{primary_indicator}\n"
            if cal.get("description"):
                calendar_list += f"   Description: {cal['description']}\n"
            calendar_list += f"   ID: {cal['id']}\n"
            calendar_list += f"   Access Role: {cal['access_role']}\n\n"

        print(calendar_list)

        print("Enter the numbers of calendars you want to include (comma-separated), or 'all' for all calendars:")
        selection = input("> ").strip()

        selected_calendars = []

        if selection.lower() == "all":
            selected_calendars = calendars
        else:
            try:
                indices = [int(idx.strip()) - 1 for idx in selection.split(",")]
                for idx in indices:
                    if 0 <= idx < len(calendars):
                        selected_calendars.append(calendars[idx])
                    else:
                        print(f"Warning: Index {idx + 1} is out of range and will be ignored.")
            except ValueError:
                print("Invalid selection. Please run the setup again and enter valid numbers.")
                return

        if not selected_calendars:
            print("No calendars were selected. Configuration not saved.")
            return

        # Build config
        config = {
            "calendars": [
                {
                    "id": cal["id"],
                    "name": cal["summary"],
                    "enabled": True,
                    "primary": cal.get("primary", False),
                }
                for cal in selected_calendars
            ]
        }

        # Ensure primary is included
        has_primary = any(cal.get("primary", False) for cal in selected_calendars)
        if not has_primary:
            for cal in calendars:
                if cal.get("primary", False):
                    config["calendars"].append({
                        "id": cal["id"],
                        "name": cal["summary"],
                        "enabled": True,
                        "primary": True,
                    })
                    break

        _save_calendar_config(config)
        print(f"Calendar configuration saved. {len(config['calendars'])} calendars configured.")

    except Exception as e:
        print(f"Error setting up calendar configuration: {str(e)}")


@app.command()
def list_calendars(
    *,
    toolspec: bool = False,
):
    """List available Google Calendars and their configuration status.

    This tool lists all calendars available to the user and indicates which ones
    are currently enabled in the configuration.
    """
    if toolspec:
        print(json.dumps(generate_schema(list_calendars, "calendar_list_calendars")))
        return

    try:
        service = _get_service()
        calendars = _list_available_calendars(service)

        if not calendars:
            print("No calendars found in your Google account.")
            return

        config = _get_calendar_config()
        enabled_calendar_ids = []

        if config:
            enabled_calendar_ids = [
                cal["id"]
                for cal in config.get("calendars", [])
                if cal.get("enabled", True)
            ]

        calendar_list = "Your Google Calendars:\n\n"

        for i, cal in enumerate(calendars, 1):
            is_enabled = cal["id"] in enabled_calendar_ids
            primary_indicator = " (primary)" if cal.get("primary", False) else ""
            enabled_indicator = " [ENABLED]" if is_enabled else " [NOT ENABLED]"

            calendar_list += f"{i}. {cal['summary']}{primary_indicator}{enabled_indicator}\n"
            if cal.get("description"):
                calendar_list += f"   Description: {cal['description']}\n"
            calendar_list += f"   ID: {cal['id']}\n"
            calendar_list += f"   Access Role: {cal['access_role']}\n\n"

        if not config:
            calendar_list += "\nNo calendar configuration found. Run 'setup' command to configure your calendars."

        print(calendar_list)

    except Exception as e:
        print(f"Error listing calendars: {str(e)}")


@app.default
def main(*, toolspec: bool = False, authorize: bool = False):
    """Google Calendar tools for event management.

    Available commands: list_events, create_event, delete_event, search_events, setup, list_calendars
    """
    if toolspec:
        specs = generate_schemas_for_commands([
            (list_events, "calendar_list_events"),
            (create_event, "calendar_create_event"),
            (delete_event, "calendar_delete_event"),
            (search_events, "calendar_search"),
            (setup, "calendar_setup"),
            (list_calendars, "calendar_list_calendars"),
        ])
        print(json.dumps(specs))
        return

    if authorize:
        is_valid, message = check_credentials(CALENDAR_SCOPES, "calendar_token.pickle")
        if is_valid:
            print(json.dumps({"success": True, "message": message}))
        else:
            try:
                get_credentials(CALENDAR_SCOPES, "calendar_token.pickle")
                print(json.dumps({"success": True, "message": "Authorization successful"}))
            except Exception as e:
                print(json.dumps({"success": False, "message": str(e)}))
        return

    print("Google Calendar tools for event management.")
    print("\nAvailable commands:")
    print("  list_events     - List upcoming events")
    print("  create_event    - Create a new event")
    print("  delete_event    - Delete an event")
    print("  search_events   - Search for events by keyword")
    print("  setup           - Configure which calendars to use")
    print("  list_calendars  - List all available calendars")
    print("\nRun with --help for details, or use --toolspec for API spec.")


if __name__ == "__main__":
    app()
