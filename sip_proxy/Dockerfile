FROM python:3.12-slim

WORKDIR /app

COPY sip_proxy.py /app/sip_proxy.py

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/sip_proxy.py"]
