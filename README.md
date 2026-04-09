# ENI Juggler

Web tool for editing EtherCAT Network Information (ENI) XML files.

## Setup

**Requirements:** Python 3.10+

```bash
git clone git@github.com:A-Common-Guy/Eni_juggler.git
cd advanced_eni_juggler
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8010
```

Open [http://localhost:8010](http://localhost:8010).

## AI Assistant (optional)

Get a free API key at [console.groq.com](https://console.groq.com), then either:

```bash
# option A — environment variable
export GROQ_API_KEY=gsk_...
```

```ini
# option B — create a .env file in the project root
GROQ_API_KEY="gsk_..."
```

Or set it directly in the UI via the ⚙ button in the AI panel.
