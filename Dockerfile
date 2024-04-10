FROM ubuntu:23.10
ARG DEBIAN_FRONTEND=noninteractive
ARG APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn

RUN apt-get update 
RUN apt-get install --no-install-recommends --fix-missing -y \
    jq python3-pip  gdal-bin proj-data libxml2-utils nano
	
	




RUN apt-get install -y libimage-exiftool-perl
RUN apt-get install -y ffmpeg

RUN mkdir /opt/commonsbot

RUN chmod  --recursive 777 /opt/commonsbot

WORKDIR /opt/commonsbot
COPY requirements.txt requirements.txt
RUN pip3 install  --break-system-packages -r requirements.txt 


CMD ["/bin/bash"]
