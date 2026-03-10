from google import genai
import os
from dotenv import load_dotenv


load_dotenv()
# Configure client
client = genai.Client(api_key=os.getenv("API_KEY") )  # replace with your API key

def generate_summary(text):
    prompt = f"""
Summarize this grant opportunity in one concise sentence.
Focus on the goal of the grant and the target group.

Grant text:
{text}
"""
    try:
        # Pass the prompt as a plain string
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt  # simple string is automatically converted internally
        )
        return response.text.strip()

    except Exception as e:
        print("Gemini error:", e)
        return ""

# Example text to summarize
grant_text = """
Small Grants for Community Education Projects in Central & South America, Luena Foundation. *Closing soon!*

Luena Foundation invites locally led organizations across Central and South America to apply for small grants that expand access to education, improve learning environments, and create inclusive opportunities for children to learn and thrive. The foundation seeks grassroots initiatives that prioritize equity and inclusion, especially for Indigenous, Afro-descendant, migrant, and rural learners. Eligible projects may include literacy and reading programs for girls, classroom repairs, school supply distribution, community-based libraries, or support for transport and exam fees. At least 25% community contribution is required (cash or in-kind), and grants must be implemented within 12 months.

Geographies: Belize, Costa Rica, El Salvador, Guatemala, Honduras, Mexico, Nicaragua, Panama, Argentina, Bolivia, Brazil, Chile, Colombia, Ecuador, Paraguay, Peru, Uruguay, Venezuela (case-by-case), Dominican Republic, Haiti (case-by-case), Jamaica, Saint Lucia, Grenada, Saint Vincent and the Grenadines.

Who can apply: Locally led grassroots, nonprofit, or community-based organisations.

Funding amount: USD $1,000–1,500; 25% in-kind or cash match required.

Targeted Sectors / SDGs: Education; Focus areas: girls’ literacy, Indigenous inclusion, classroom infrastructure, youth retention.

Deadline: December 15, 2025.

Learn more and apply here.

Luena backs small but high-impact projects designed and led by the very communities they seek to uplift.
"""

# Run summary
ai_summary = generate_summary(grant_text)
print("AI Summary:", ai_summary)
