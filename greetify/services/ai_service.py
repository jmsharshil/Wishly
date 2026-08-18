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
        "You are a real person typing a quick message on WhatsApp to someone in your contacts. "
        "DO NOT sound poetic, overly dramatic, formal, or like an AI/greeting card. "
        "Your message must be short, casual, and sound exactly like a real human sending a text message. "
        "CRITICAL INSTRUCTIONS:\n"
        "1. Keep it concise: Real people write 1 to 3 short sentences max on WhatsApp. Do NOT write long paragraphs.\n"
        "2. Natural Language: Use everyday conversational words. Do not use heavy vocabulary or poetic metaphors.\n"
        "3. Tone Matching: Strictly follow the 'Tags'. If tags say 'Professional', keep it polite. If tags imply 'Close/Family', be very casual and warm.\n"
        "4. Use Notes: YOU MUST incorporate any details provided in 'Specific context' or notes. If a specific memory, detail, or inside joke is provided, include it naturally in the message.\n"
        "5. Format: Output ONLY the message text. No placeholders, no quotes, no markdown, no intros. Ready to be copied and pasted."
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
