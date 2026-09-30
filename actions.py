import json
import re

def parse_command(command):
    """Parses a simple command and returns a list of actions."""
    command = command.lower()
    
    # Check for Slack message
    if "message" in command and "on slack" in command:
        # ... (Simple regex to find who and what) ...
        return [{"type": "slack.send_message", "args": {"to": "U03SARAHK", "text": "..."}}]
        
    # Check for email
    if "email" in command:
        # ... (Simple regex to find who and what) ...
        return [{"type": "gmail.send", "args": {"to": ["..."]}}]
        
    # Check for reminder
    if "remind me" in command:
        # ... (Simple regex to find what and when) ...
        return [{"type": "reminder.create", "args": {"text": "...", "due": "..."}}]
        
    # ... (Add other simple rules for calendar, etc.) ...
    
    return [{"type": "clarify", "args": {"question": "I didn't understand that command."}}]

# --- MAIN ---
def main():
    # ... (Code to read commands, call parse_command(),
    # and write the output file) ...
    pass

if __name__ == "__main__":
    main()