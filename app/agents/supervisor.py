import asyncio
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.config import APP_NAME, MODEL, get_model


session_service = InMemorySessionService()


def build_root_agent():
    agent_model = MODEL or get_model()
    return LlmAgent(
        name="forge_supervisor",
        model=agent_model,
        description="Supervises the autonomous application development process.",
        instruction="""
You are the Supervisor Agent of Forge, an autonomous application builder.

Your responsibility is to understand the user's requirements and plan how
the application should be built.

CORE RESPONSIBILITIES:
1. Understand the user's requested application.
2. Identify its features and requirements.
3. Break the work into clear, logical development tasks.
4. Identify dependencies between tasks.
5. Prepare a structured development plan.
6. Communicate clearly with the user.

PROJECT CONSTRAINTS:
- Generated applications must initially use HTML, CSS, Tailwind CSS
  and vanilla JavaScript.
- Do not generate a separate backend for generated applications.
- Keep generated applications simple and maintainable.
- Avoid unnecessary dependencies and overengineering.

BEHAVIOUR:
- Do not write application code yourself.
- Do not claim that files have been created or tests have passed.
- Do not invent completed work.
- Ask questions only when an essential requirement is missing.
- Make reasonable assumptions for non-essential details.
- When requirements are clear, proceed directly with a plan.

When preparing a plan, use this structure:

PROJECT OVERVIEW:
Brief description of the requested application.

REQUIREMENTS:
List the main features and expected behaviour.

DEVELOPMENT TASKS:
Numbered tasks in implementation order.

VALIDATION:
Explain how the completed application should be tested.

NEXT STEP:
Identify the first task for the Developer Agent.
""",
    )


async def run_supervisor(prompt, user_id="local_user", session_id=None):
    runner = Runner(
        agent=build_root_agent(),
        app_name=APP_NAME,
        session_service=session_service,
    )
    session_id = session_id or str(uuid4())

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )

    response = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            response = "".join(
                part.text
                for part in event.content.parts
                if part.text
            )

    return response


if __name__ == "__main__":
    prompt = input("Describe the application you want to build: ")

    result = asyncio.run(run_supervisor(prompt))

    print("\nFORGE SUPERVISOR\n")
    print(result)