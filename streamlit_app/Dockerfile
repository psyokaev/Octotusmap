# Build context = thư mục gốc dự án (xem docker-compose.yml)
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
RUN pip install --no-cache-dir "streamlit>=1.45" "plotly>=5.24" "folium>=0.17" "streamlit-folium>=0.22" httpx
COPY streamlit_app/ .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
