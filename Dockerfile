FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aiops_sim/ aiops_sim/

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/reports && chown appuser /app/reports
USER appuser

ENTRYPOINT ["python", "-m", "aiops_sim"]
CMD ["run", "--out-dir", "reports"]
