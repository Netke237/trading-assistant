from fastapi import FastAPI

app = FastAPI(
    title="Options Screener API",
    version="0.1.0",
    description="Backend API for the Options Screener and Recommendation Assistant."
)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "options-screener"}
