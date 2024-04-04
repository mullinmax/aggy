ARG BASE_IMAGE=blinder-shared:latest
FROM $BASE_IMAGE as base

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the content of the local src directory to the working directory
COPY . .

EXPOSE 8000

# Specify the command to run on container start
CMD ["python", "main.py"]
