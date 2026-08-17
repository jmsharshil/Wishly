import os
from openai import OpenAI, AzureOpenAI
from django.conf import settings

def generate_wish(event, language, additional_notes=""):
    """
    Generates a wish using OpenAI based on event type, relation, tags, and language.
    """
    endpoint_url = os.environ.get("ENDPOINT_URL", "").strip()
    api_key = os.environ.get("OPENAI_API_KEY")
    
    # Check if this is an Azure OpenAI key
    if endpoint_url and 'azure.com' in endpoint_url:
        client = AzureOpenAI(
            api_key=api_key,
            api_version="2023-12-01-preview",
            azure_endpoint=endpoint_url
        )
        # Note: In Azure, 'model' must match your exact deployment name.
        # Often it is named 'gpt-35-turbo' or 'gpt-4'.
        model_name = "gpt-4o-mini" 
    else:
        client = OpenAI(api_key=api_key)
        model_name = "gpt-3.5-turbo"

    # Build a highly contextual prompt
    tags_context = f"Tags describing relationship/tone: {event.tags}." if event.tags else ""
    user_notes = f"{event.notes_for_ai} {additional_notes}".strip()
    prompt = f"Write a personalized {event.event_type.lower()} wish for {event.name}.\n"
    if tags_context:
        prompt += f"{tags_context}\n"
    if user_notes:
        prompt += f"Specific context: {user_notes}\n"
        
    prompt += f"\nCRITICAL: Write the final wish fluently in the language represented by the code '{language}' (for example, if the code is 'gu', write in Gujarati; if 'es', write in Spanish). Ensure perfect grammar and natural phrasing."

    system_msg = (
        "You are a human writing a heartfelt message to a person in your life. "
        "DO NOT sound like an AI, a generic greeting card, or a corporate bot. "
        "Your message must sound 100% natural, casual, and emotionally genuine, exactly as a real person would type it on WhatsApp or in a text message. "
        "CRITICAL INSTRUCTIONS:\n"
        "1. Grammar & Language: Ensure flawless grammar, syntax, and natural vocabulary in the requested language. Use colloquialisms where appropriate to make it sound human.\n"
        "2. Tone Matching: If tags imply 'Professional', be polite but human. If tags imply 'Close/Family/Friend', be warm, casual, use emojis naturally, and speak from the heart.\n"
        "3. Format: Output ONLY the final message ready to be sent. No placeholders, no introductions, no quotes around the text. DO NOT use any markdown formatting (like **bold**, *italics*, or #). Just plain text and emojis."
    )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI Error: {e}")
        return "Sorry, could not generate a wish at this time."
