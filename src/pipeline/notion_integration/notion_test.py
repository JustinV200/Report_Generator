"""
NOTION INTEGRATION TEST

Passes in a hardcoded title and summary string to test the passing to Notion
Requires push_to_notion from notion.py
"""
import requests

from pipeline.notion_integration.notion import push_to_notion, push_analysis_to_notion

'''    Fake data for testing     '''

extracted_data = {
    "title": "An Analysis of Anthropic AI’s Impact on AI Safety and National Security",
    "summary": "This text claims that Anthropic has developed AI models called 'Claude Mythos'"
               " and 'Project Glasswing' that found thousands of software vulnerabilities, and that "
               "Anthropic is collaborating with OpenAI on cybersecurity efforts. It argues this raises "
               "urgent questions about AI safety regulation and cyber threats to critical infrastructure."
}

analysis = {
    "synthesis": {
        "title": extracted_data["title"],
        "executive_summary": extracted_data["summary"],
        "themes": [
            {
                "theme": "AI Safety Regulation",
                "insights": [
                    "Anthropic's models have identified thousands of software vulnerabilities, raising questions about oversight.",
                    "Collaboration between Anthropic and OpenAI on cybersecurity blurs competitive boundaries."
                ]
            },
            {
                "theme": "National Security Implications",
                "insights": [
                    "AI-discovered vulnerabilities in critical infrastructure pose novel threat vectors.",
                    "Government agencies lack frameworks to respond to AI-assisted cyber operations at scale."
                ]
            }
        ],
        "key_takeaways": [
            "Anthropic's Project Glasswing found vulnerabilities across critical infrastructure sectors.",
            "Joint AI safety efforts between leading labs may accelerate both risk and mitigation.",
            "Existing cybersecurity regulation is not designed for AI-speed threat discovery."
        ]
    }
}

def push_to_notion_test():
    """
    Specifically tests the connection to the Notion API.  Meant for verifying credentials and database connection
    """
    try:
        push_to_notion(extracted_data)
        print("Successfully pushed to Notion")
    except EnvironmentError as e:
        print("Failed to push to Notion: " + str(e))
    except requests.HTTPError as e:
        print("Failed to push to Notion: " + str(e))


def push_analysis_to_notion_test():
    """
    Tests sending a full analysis to Notion.  Includes the same Title and Summary as before, but now adds the analysis
    a page linked to the database row.
    """
    try:
        push_analysis_to_notion(analysis)
        print("Successfully pushed to Notion")
    except EnvironmentError as e:
        print("Failed to push to Notion: " + str(e))
    except requests.HTTPError as e:
        print("Failed to push to Notion: " + str(e))



def main():
    print(" ---- Testing notion_integration files ---- ")
    print("Which method would you like to test?\n"
          "1: push_to_notion: Pushes data to Notion\n"
          "2: push_analysis_to_notion: Pushes analysis to Notion\n"
          "3: All of the above")
    choice = input("")

    if choice == "1":
        push_to_notion_test()
    elif choice == "2":
        push_analysis_to_notion_test()
    elif choice == "3":
        push_to_notion_test()
        push_analysis_to_notion_test()
    else:
        print("Invalid choice")
        return

if __name__ == "__main__":
    main()