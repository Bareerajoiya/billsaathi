# 💡 BillSaathi

**My app helps Pakistani households understand their electricity bill using Gemma 4.**

Upload a photo of an electricity bill. Gemma 4 reads the numbers, plain Python checks them, and Gemma 4 explains the result in English, Roman Urdu or Urdu, with next steps and a polite draft request to the sub-division office. BillSaathi never says a bill is wrong; it only says what is worth verifying.

## How Gemma 4 is used
- **Read:** Gemma 4 (vision) turns the bill photo into structured data. It only copies numbers and never calculates.
- **Check:** plain Python (`checks.py`) verifies readings, billing days, usage history and protected status. No AI is used here, so the same bill always gives the same result.
- **Explain:** Gemma 4 writes the explanation in the chosen language.
- Models: `gemma-4-31b-it` and `gemma-4-26b-a4b-it`, called through the **Gemini API (Google AI Studio)**.

## Licenses
- Model: Gemma 4, released under **Apache 2.0**.
- This project: **MIT License**.

## Run it
```bash
git clone https://github.com/Bareerajoiya/billsaathi.git
cd billsaathi
pip install -r requirements.txt
# create a .env file with: GEMINI_API_KEY=your_key
streamlit run app.py
```
Set `MOCK_MODEL=1` in `.env` for demo mode (sample data, no API call).

## Privacy
The photo is never saved. Only numbers, checks and explanations are stored in a local SQLite file. The model is told not to read names, addresses, CNIC, reference or meter numbers.

## Limits
Not an official tool of any electricity company. Compare the numbers with your paper bill. The 200-unit protected-consumer limit in `checks.py` is an assumption that must be confirmed with the distribution company.