from datetime import timedelta

import yaml
from googleapiclient.discovery import build

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool

from silica.developer.tools.google_shared import CONFIG_DIR
from silica.developer.tools.google_shared import ensure_config_dir, get_credentials

CALENDAR_CONFIG_PATH = CONFIG_DIR / "google-calendar.yml"


def save_calendar_config(config):
    """Save the calendar configuration.

    Args:
        config: Configuration dictionary to save
    """
    ensure_config_dir()
    with open(CALENDAR_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def get_user_timezone(service, calendar_id="primary"):
    """Get the user's calendar timezone.

    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to check (default: primary)

    Returns:
        String containing timezone ID (e.g., 'America/Los_Angeles') or 'UTC' as fallback
    """
    try:
        calendar_info = service.calendars().get(calendarId=calendar_id).execute()
        return calendar_info.get("timeZone", "UTC")
    except Exception as e:
        print(f"Error getting calendar timezone: {str(e)}")
        return "UTC"


def get_calendar_config():
    """Get the calendar configuration.

    Returns:
        Dictionary containing calendar configuration or None if not configured
    """
    if not CALENDAR_CONFIG_PATH.exists():
        return None

    with open(CALENDAR_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def list_available_calendars():
    """List all available calendars for the user.

    Returns:
        List of dictionaries containing calendar information
    """
    # Get credentials for Calendar API
    creds = get_credentials(CALENDAR_SCOPES, token_file="calendar_token.pickle")
    service = build("calendar", "v3", credentials=creds)

    # Get the calendar list
    calendar_list = service.calendarList().list().execute()

    calendars = []
    for calendar_entry in calendar_list.get("items", []):
        calendars.append(
            {
                "id": calendar_entry["id"],
                "summary": calendar_entry.get("summary", "Unnamed Calendar"),
                "description": calendar_entry.get("description", ""),
                "primary": calendar_entry.get("primary", False),
                "access_role": calendar_entry.get("accessRole", ""),
            }
        )

    return calendars


@tool
def calendar_setup(context: "AgentContext") -> str:
    """Set up Google Calendar configuration by listing and selecting which calendars to enable.

    This tool guides the user through an interactive setup process to configure which
    Google Calendars should be visible and usable through the calendar tools.

    Args:
        (No additional arguments needed)
    """
    try:
        # Check if config already exists
        existing_config = get_calendar_config()
        if existing_config:
            calendars = existing_config.get("calendars", [])
            enabled_calendars = [cal for cal in calendars if cal.get("enabled", False)]

            # Ask if user wants to reconfigure
            print(
                f"Calendar configuration already exists with {len(enabled_calendars)} enabled calendars."
            )
            print("Do you want to reconfigure? (y/n)")
            response = input("> ").strip().lower()
            if response != "y":
                return "Keeping existing calendar configuration."

        # List all available calendars
        print("Fetching available calendars from Google...")
        calendars = list_available_calendars()

        if not calendars:
            return "No calendars found in your Google account."

        # Create a formatted list of calendars for display
        calendar_list = "Available calendars:\n\n"
        for i, cal in enumerate(calendars, 1):
            primary_indicator = " (primary)" if cal.get("primary", False) else ""
            calendar_list += f"{i}. {cal['summary']}{primary_indicator}\n"
            if cal.get("description"):
                calendar_list += f"   Description: {cal['description']}\n"
            calendar_list += f"   ID: {cal['id']}\n"
            calendar_list += f"   Access Role: {cal['access_role']}\n\n"

        # Print the calendar list
        print(calendar_list)

        # Get user selection
        print(
            "Enter the numbers of calendars you want to include (comma-separated), or 'all' for all calendars:"
        )
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
                        print(
                            f"Warning: Index {idx+1} is out of range and will be ignored."
                        )
            except ValueError:
                return "Invalid selection. Please run the setup again and enter valid numbers."

        if not selected_calendars:
            return "No calendars were selected. Configuration not saved."

        # Create the configuration
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

        # Find the primary calendar if not already included
        has_primary = any(cal.get("primary", False) for cal in selected_calendars)
        if not has_primary:
            for cal in calendars:
                if cal.get("primary", False):
                    config["calendars"].append(
                        {
                            "id": cal["id"],
                            "name": cal["summary"],
                            "enabled": True,
                            "primary": True,
                        }
                    )
                    break

        # Save the configuration
        save_calendar_config(config)

        return f"Calendar configuration saved. {len(config['calendars'])} calendars configured."

    except Exception as e:
        return f"Error setting up calendar configuration: {str(e)}"


def get_enabled_calendars():
    """Get a list of enabled calendars from the configuration.

    Returns:
        List of enabled calendar dictionaries, or None if not configured
    """
    config = get_calendar_config()
    if not config:
        return None

    return [cal for cal in config.get("calendars", []) if cal.get("enabled", True)]


@tool
def calendar_list_events(
    context: "AgentContext",
    days: int = 7,
    calendar_id: str = None,
    start_date: str = None,
    end_date: str = None,
) -> str:
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
    try:
        # Check if calendar configuration exists
        config = get_calendar_config()
        if not config and not calendar_id:
            return (
                "No calendar configuration found. Please run calendar_setup first, "
                "or specify a calendar_id."
            )

        # Get credentials for Calendar API
        creds = get_credentials(CALENDAR_SCOPES, token_file="calendar_token.pickle")
        service = build("calendar", "v3", credentials=creds)

        # Get the user's timezone from calendar settings
        user_timezone = get_user_timezone(
            service, calendar_id if calendar_id else "primary"
        )

        # Calculate time range based on parameters
        if start_date and end_date:
            # Use the provided date range
            try:
                # Parse dates in user's local timezone
                from datetime import datetime
                import pytz

                local_tz = pytz.timezone(user_timezone)

                # Create timezone-aware datetime objects for start and end of day in local timezone
                start_time = local_tz.localize(
                    datetime.strptime(start_date, "%Y-%m-%d")
                )
                end_time = local_tz.localize(
                    datetime.strptime(end_date, "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59
                    )
                )

                # Convert to UTC for API query
                start_time = start_time.astimezone(pytz.UTC)
                end_time = end_time.astimezone(pytz.UTC)

                date_range_description = f"from {start_date} to {end_date}"
            except ValueError:
                return "Invalid date format. Please use YYYY-MM-DD format for dates."
        else:
            # Use the days parameter
            import pytz
            from datetime import datetime

            local_tz = pytz.timezone(user_timezone)

            # Get current time in user's local timezone
            now = datetime.now(local_tz)

            # Start from the beginning of the current day
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=days)

            # Convert to UTC for API query
            start_time = start_time.astimezone(pytz.UTC)
            end_time = end_time.astimezone(pytz.UTC)

            date_range_description = f"in the next {days} days"

        # Determine which calendars to query
        calendars_to_query = []
        if calendar_id:
            # Just query the specified calendar
            calendars_to_query.append({"id": calendar_id, "name": "Specified Calendar"})
        else:
            # Query all enabled calendars from config
            enabled_calendars = get_enabled_calendars()
            if not enabled_calendars:
                return "No enabled calendars found in configuration. Please run calendar_setup first."
            calendars_to_query = enabled_calendars

        # Get events from all calendars
        all_events = []

        for cal in calendars_to_query:
            # Format properly for RFC 3339 format required by Google Calendar API
            # Note: Don't append 'Z' to a datetime that already has timezone info
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

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

            events = events_result.get("items", [])
            for event in events:
                event["calendar_name"] = cal.get("name", "Unknown Calendar")
                all_events.append(event)

        # Sort all events by start time
        all_events.sort(
            key=lambda x: x["start"].get("dateTime", x["start"].get("date"))
        )

        if not all_events:
            return f"No events found {date_range_description}."

        # Group events by date
        events_by_date = {}

        for event in all_events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))

            # Format date/time in user's timezone
            if "T" in start:  # This is a datetime, not just a date
                import pytz

                # Parse the datetime strings to datetime objects
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))

                # Convert to user's timezone
                local_tz = pytz.timezone(user_timezone)
                start_local = start_dt.astimezone(local_tz)
                end_local = end_dt.astimezone(local_tz)

                # Format with local time
                time_str = f"{start_local.strftime('%H:%M')} to {end_local.strftime('%H:%M')} ({user_timezone})"

                # Get the local date for grouping
                event_date = start_local.strftime("%Y-%m-%d")
            else:
                time_str = "(all day)"
                event_date = start.split("T")[0] if "T" in start else start

            # Get attendees if any
            attendees = []
            if "attendees" in event:
                attendees = [
                    attendee.get("email", "Unknown") for attendee in event["attendees"]
                ]

            def _make_busy(e):
                return f"Busy ({e['calendar_name']})"

            # Format event
            event_text = (
                f"Event: {event.get('summary', _make_busy(event))}\n"
                f"Calendar: {event['calendar_name']}\n"
                f"Date: {event_date}\n"
                f"Time: {time_str}\n"
                f"Creator: {event.get('creator', {}).get('displayName', 'Unknown')}\n"
            )

            # Add location if present
            if "location" in event:
                event_text += f"Location: {event['location']}\n"

            # Add description if present
            if "description" in event and event["description"].strip():
                # Truncate long descriptions
                description = event["description"]
                if len(description) > 200:
                    description = description[:197] + "..."
                event_text += f"Description: {description}\n"

            # Add attendees if present
            if attendees:
                event_text += f"Attendees: {', '.join(attendees)}\n"

            # Add event ID
            event_text += f"ID: {event['id']}\n"

            # Add to events by date dictionary
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event_text)

        # If no events found
        if not events_by_date:
            return f"No events found {date_range_description}."

        # Format output with events grouped by date
        formatted_output = []
        for date in sorted(events_by_date.keys()):
            formatted_output.append(f"Events for {date}:")
            formatted_output.append("\n---\n".join(events_by_date[date]))

        return f"Upcoming events {date_range_description}:\n\n" + "\n\n".join(
            formatted_output
        )

    except Exception as e:
        return f"Error listing calendar events: {str(e)}"


@tool
def calendar_create_event(
    context: "AgentContext",
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
    calendar_id: str = None,
) -> str:
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
    try:
        # If no calendar_id is specified, use the primary calendar from config or 'primary'
        if not calendar_id:
            config = get_calendar_config()
            if config:
                calendars = config.get("calendars", [])
                primary_calendars = [
                    cal
                    for cal in calendars
                    if cal.get("primary", False) and cal.get("enabled", True)
                ]
                if primary_calendars:
                    calendar_id = primary_calendars[0]["id"]
                else:
                    calendar_id = "primary"
            else:
                calendar_id = "primary"

        # Get credentials for Calendar API
        creds = get_credentials(CALENDAR_SCOPES, token_file="calendar_token.pickle")
        service = build("calendar", "v3", credentials=creds)

        # Determine if this is an all-day event
        is_all_day = "T" not in start_time

        # Create the event object
        event = {
            "summary": summary,
            "description": description,
            "location": location,
        }

        # Set start and end times
        if is_all_day:
            # All-day events don't need timezone info, just use the date
            event["start"] = {
                "date": start_time.split("T")[0] if "T" in start_time else start_time
            }
            event["end"] = {
                "date": end_time.split("T")[0] if "T" in end_time else end_time
            }
        else:
            # Get user's calendar timezone
            try:
                # Get the calendar's timezone from API
                calendar_info = (
                    service.calendars().get(calendarId=calendar_id).execute()
                )
                user_timezone = calendar_info.get("timeZone", "UTC")
            except Exception as e:
                # Log the error and fallback to UTC
                print(f"Error getting calendar timezone: {str(e)}")
                user_timezone = "UTC"

            # Check if timezone is already specified in the datetime strings
            # Safely check for timezone markers (Z, +, or - after time part)
            def has_timezone(dt_str):
                if dt_str.endswith("Z"):
                    return True

                # Check for proper ISO format with time part
                time_part_pos = dt_str.find("T")
                if time_part_pos == -1:
                    return False  # Not a datetime string with time

                # Standard format should be YYYY-MM-DDThh:mm:ss[.sss](+/-hh:mm or Z)
                # Look for +/- but make sure it's not the date separator
                # Also confirm we have proper time format with colons
                time_part = dt_str[time_part_pos + 1 :]
                if ":" not in time_part:
                    return False  # Not a properly formatted time

                # Look for timezone markers after the seconds
                for pos in range(
                    time_part_pos + 8, len(dt_str)
                ):  # At least hh:mm:ss after T
                    if dt_str[pos] in ("+", "-"):
                        return True

                return False

            # If timestamps don't have timezone info, interpret them in the user's local timezone
            # and convert to proper ISO format with timezone info
            import pytz
            from datetime import datetime

            has_timezone_start = has_timezone(start_time)
            has_timezone_end = has_timezone(end_time)

            local_tz = pytz.timezone(user_timezone)

            # Handle start time
            if has_timezone_start:
                # User specified timezone, respect it
                event["start"] = {"dateTime": start_time}
            else:
                # No timezone in string, assume it's in local timezone and convert to ISO
                if "T" in start_time:  # It's a datetime
                    # Parse the datetime in the local timezone
                    local_dt = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")
                    # Make it timezone-aware
                    aware_dt = local_tz.localize(local_dt)
                    # Convert to ISO 8601 format with timezone info
                    iso_dt = aware_dt.isoformat()
                    # Use this for the event
                    event["start"] = {"dateTime": iso_dt}
                else:
                    # It's just a date (all-day event)
                    event["start"] = {"dateTime": start_time, "timeZone": user_timezone}

            # Handle end time
            if has_timezone_end:
                # User specified timezone, respect it
                event["end"] = {"dateTime": end_time}
            else:
                # No timezone in string, assume it's in local timezone and convert to ISO
                if "T" in end_time:  # It's a datetime
                    # Parse the datetime in the local timezone
                    local_dt = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S")
                    # Make it timezone-aware
                    aware_dt = local_tz.localize(local_dt)
                    # Convert to ISO 8601 format with timezone info
                    iso_dt = aware_dt.isoformat()
                    # Use this for the event
                    event["end"] = {"dateTime": iso_dt}
                else:
                    # It's just a date (all-day event)
                    event["end"] = {"dateTime": end_time, "timeZone": user_timezone}

        # Add attendees if specified
        if attendees:
            attendee_list = [{"email": email.strip()} for email in attendees.split(",")]
            event["attendees"] = attendee_list

        # Create the event
        event = service.events().insert(calendarId=calendar_id, body=event).execute()

        # Try to get calendar name
        try:
            calendar_info = service.calendars().get(calendarId=calendar_id).execute()
            calendar_name = calendar_info.get("summary", calendar_id)
        except:  # noqa: E722
            calendar_name = calendar_id

        return (
            f"Event created successfully in calendar '{calendar_name}'.\n"
            f"Event ID: {event['id']}\n"
            f"Title: {summary}\n"
            f"Time: {start_time} to {end_time}"
        )

    except Exception as e:
        return f"Error creating calendar event: {str(e)}"


@tool
def calendar_delete_event(
    context: "AgentContext", event_id: str, calendar_id: str = None
) -> str:
    """Delete an event from Google Calendar.

    Args:
        event_id: ID of the event to delete
        calendar_id: ID of the calendar containing the event (default: None, requiring confirmation)
    """
    try:
        # Get credentials for Calendar API
        creds = get_credentials(CALENDAR_SCOPES, token_file="calendar_token.pickle")
        service = build("calendar", "v3", credentials=creds)

        # If no calendar_id provided, search in all enabled calendars
        if not calendar_id:
            enabled_calendars = get_enabled_calendars()
            if not enabled_calendars:
                return (
                    "No calendar configuration found. Please provide the calendar_id."
                )

            # First try to find the event to get its details before deletion
            event_found = False
            event_summary = "Unknown Event"

            for cal in enabled_calendars:
                try:
                    event = (
                        service.events()
                        .get(calendarId=cal["id"], eventId=event_id)
                        .execute()
                    )
                    calendar_id = cal["id"]
                    event_found = True
                    event_summary = event.get("summary", "Unknown Event")
                    break
                except:  # noqa: E722
                    continue

            if not event_found:
                return (
                    f"Event {event_id} not found in any of your configured calendars."
                )

            # Confirm deletion
            print(
                f"Found event '{event_summary}' in calendar '{cal.get('name', calendar_id)}'"
            )
            print("Are you sure you want to delete this event? (y/n)")
            response = input("> ").strip().lower()
            if response != "y":
                return "Event deletion cancelled."

        # Delete the event
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

        return f"Event {event_id} deleted successfully."

    except Exception as e:
        return f"Error deleting calendar event: {str(e)}"


@tool
def calendar_search(
    context: "AgentContext", query: str, days: int = 90, calendar_id: str = None
) -> str:
    """Search for events in Google Calendar by keyword.

    This tool allows you to search for calendar events containing specific keywords
    in their title, description, or location.

    Args:
        query: The search term to look for in events
        days: Number of days to look ahead (default: 90)
        calendar_id: ID of the calendar to search (default: None, which searches all enabled calendars)
    """
    try:
        # Check if calendar configuration exists
        config = get_calendar_config()
        if not config and not calendar_id:
            return (
                "No calendar configuration found. Please run calendar_setup first, "
                "or specify a calendar_id."
            )

        # Get credentials for Calendar API
        creds = get_credentials(CALENDAR_SCOPES, token_file="calendar_token.pickle")
        service = build("calendar", "v3", credentials=creds)

        # Get the user's timezone
        user_timezone = get_user_timezone(
            service, calendar_id if calendar_id else "primary"
        )

        # Calculate time range in user's local timezone
        import pytz
        from datetime import datetime

        local_tz = pytz.timezone(user_timezone)

        # Get current time in user's local timezone
        now = datetime.now(local_tz)
        start_time = now - timedelta(days=days)
        end_time = now + timedelta(days=days)

        # Description for output
        date_range_description = f"in the next {days} days"

        # Convert to UTC for API query
        start_time = start_time.astimezone(pytz.UTC)
        end_time = end_time.astimezone(pytz.UTC)

        # Determine which calendars to query
        calendars_to_query = []
        if calendar_id:
            # Just query the specified calendar
            calendars_to_query.append({"id": calendar_id, "name": "Specified Calendar"})
        else:
            # Query all enabled calendars from config
            enabled_calendars = get_enabled_calendars()
            if not enabled_calendars:
                return "No enabled calendars found in configuration. Please run calendar_setup first."
            calendars_to_query = enabled_calendars

        # Get events from all calendars
        all_events = []

        for cal in calendars_to_query:
            # Format properly for RFC 3339 format required by Google Calendar API
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            events_result = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=start_time_str,
                    timeMax=end_time_str,
                    singleEvents=True,
                    orderBy="startTime",
                    # We can't use q parameter here because it would only search the summary
                    # Instead, we'll filter results after receiving them
                )
                .execute()
            )

            events = events_result.get("items", [])
            for event in events:
                event["calendar_name"] = cal.get("name", "Unknown Calendar")
                all_events.append(event)

        # Filter events that match the query
        query = query.lower()
        matching_events = []

        for event in all_events:
            # Check if query appears in summary (title)
            if query in (event.get("summary", "")).lower():
                matching_events.append(event)
                continue

            # Check if query appears in description
            if query in (event.get("description", "")).lower():
                matching_events.append(event)
                continue

            # Check if query appears in location
            if query in (event.get("location", "")).lower():
                matching_events.append(event)
                continue

            # Check if query appears in attendee emails or names
            if "attendees" in event:
                for attendee in event["attendees"]:
                    if (
                        query in attendee.get("email", "").lower()
                        or query in attendee.get("displayName", "").lower()
                    ):
                        matching_events.append(event)
                        break

        # Sort matching events by start time
        matching_events.sort(
            key=lambda x: x["start"].get("dateTime", x["start"].get("date"))
        )

        if not matching_events:
            return f"No events found matching '{query}' in the next {days} days."

        # Group events by date
        events_by_date = {}

        for event in matching_events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))

            # Format date/time in user's timezone
            if "T" in start:  # This is a datetime, not just a date
                import pytz

                # Parse the datetime strings to datetime objects
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))

                # Convert to user's timezone
                local_tz = pytz.timezone(user_timezone)
                start_local = start_dt.astimezone(local_tz)
                end_local = end_dt.astimezone(local_tz)

                # Format with local time
                time_str = f"{start_local.strftime('%H:%M')} to {end_local.strftime('%H:%M')} ({user_timezone})"

                # Get the local date for grouping
                event_date = start_local.strftime("%Y-%m-%d")
            else:
                time_str = "(all day)"
                event_date = start.split("T")[0] if "T" in start else start

            # Get attendees if any
            attendees = []
            if "attendees" in event:
                attendees = [
                    attendee.get("email", "Unknown") for attendee in event["attendees"]
                ]

            # Format event
            event_text = (
                f"Event: {event.get('summary', 'Untitled Event')}\n"
                f"Calendar: {event['calendar_name']}\n"
                f"Date: {event_date}\n"
                f"Time: {time_str}\n"
                f"Creator: {event['creator'].get('displayName', 'Unknown')}\n"
            )

            # Add location if present
            if "location" in event:
                event_text += f"Location: {event['location']}\n"

            # Add description if present
            if "description" in event and event["description"].strip():
                # Truncate long descriptions
                description = event["description"]
                if len(description) > 200:
                    description = description[:197] + "..."
                event_text += f"Description: {description}\n"

            # Add attendees if present
            if attendees:
                event_text += f"Attendees: {', '.join(attendees)}\n"

            # Add event ID
            event_text += f"ID: {event['id']}\n"

            # Add to events by date dictionary
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event_text)

        # If no events found
        if not events_by_date:
            return f"No events found matching '{query}' in the next {days} days."

        # Format output with events grouped by date
        formatted_output = []
        for date in sorted(events_by_date.keys()):
            formatted_output.append(f"Events for {date} matching '{query}':")
            formatted_output.append("\n---\n".join(events_by_date[date]))

        return (
            f"Found {len(matching_events)} events matching '{query}' {date_range_description}:\n\n"
            + "\n\n".join(formatted_output)
        )

    except Exception as e:
        return f"Error searching calendar events: {str(e)}"


@tool
def calendar_list_calendars(context: "AgentContext") -> str:
    """List available Google Calendars and their configuration status.

    This tool lists all calendars available to the user and indicates which ones
    are currently enabled in the configuration.

    Args:
        (No additional arguments needed)
    """
    try:
        # Get all available calendars from Google
        calendars = list_available_calendars()

        if not calendars:
            return "No calendars found in your Google account."

        # Get configured calendars
        config = get_calendar_config()
        enabled_calendar_ids = []

        if config:
            enabled_calendar_ids = [
                cal["id"]
                for cal in config.get("calendars", [])
                if cal.get("enabled", True)
            ]

        # Format the calendar list
        calendar_list = "Your Google Calendars:\n\n"

        for i, cal in enumerate(calendars, 1):
            is_enabled = cal["id"] in enabled_calendar_ids
            primary_indicator = " (primary)" if cal.get("primary", False) else ""
            enabled_indicator = " [ENABLED]" if is_enabled else " [NOT ENABLED]"

            calendar_list += (
                f"{i}. {cal['summary']}{primary_indicator}{enabled_indicator}\n"
            )
            if cal.get("description"):
                calendar_list += f"   Description: {cal['description']}\n"
            calendar_list += f"   ID: {cal['id']}\n"
            calendar_list += f"   Access Role: {cal['access_role']}\n\n"

        if not config:
            calendar_list += "\nNo calendar configuration found. Run calendar_setup to configure your calendars."

        return calendar_list

    except Exception as e:
        return f"Error listing calendars: {str(e)}"
