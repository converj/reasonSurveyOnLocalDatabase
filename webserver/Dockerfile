# Base image on linux with python
FROM python:3.12
RUN apt-get update

# Copy application files to image
COPY . /webserver
WORKDIR /webserver

# Install dependencies
RUN pip install -r requirements.txt

# Run python
ENTRYPOINT ["python"]
CMD ["main.py"]

