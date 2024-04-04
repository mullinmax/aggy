ARG BASE_IMAGE=blinder-shared:latest
FROM $BASE_IMAGE as base

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "./app.py"]
