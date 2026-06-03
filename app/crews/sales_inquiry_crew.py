from uuid import uuid4
from crewai import Agent, Task, Crew, Process


def run_sales_inquiry_crew(sender: str, subject: str, body: str) -> dict:
    sales_processing_agent = Agent(
        role="Sales Processing Agent",
        goal="Extract product inquiry details and retrieve relevant sales context.",
        backstory="You query Odoo ERP data and prepare structured product information.",
        verbose=True,
    )

    email_drafting_agent = Agent(
        role="Email Drafting Agent",
        goal="Generate a policy-compliant customer response draft.",
        backstory="You write professional sales replies using only approved product data.",
        verbose=True,
    )

    extract_task = Task(
        description=f"""
        Analyse this customer email.

        Sender: {sender}
        Subject: {subject}
        Body: {body}

        Extract product name, inquiry type, quantity, and missing information.
        """,
        expected_output="Structured inquiry summary.",
        agent=sales_processing_agent,
    )

    draft_task = Task(
        description="""
        Draft a professional response email using the extracted inquiry summary.
        Do not invent unavailable product data.
        Ask for missing details when needed.
        """,
        expected_output="A complete email draft for sales officer review.",
        agent=email_drafting_agent,
    )

    crew = Crew(
        agents=[sales_processing_agent, email_drafting_agent],
        tasks=[extract_task, draft_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    return {
        "draft_id": f"DFT-{uuid4().hex[:8].upper()}",
        "draft": str(result),
    }
