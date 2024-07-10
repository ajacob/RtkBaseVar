FROM debian:bullseye-slim
LABEL "GNU Affero General Public License v3 (AGPL-3.0)"="julien.ancelin@inrae.fr"

RUN \
    apt-get update \
    && apt-get install -y apt-utils \
    && apt-get install --fix-missing -y wget git procps systemd lsb-release \
        build-essential python3-pip python3-dev python3-setuptools python3-wheel socat \
        libssl-dev libcurl4-openssl-dev libssl-dev openssl \
    #install str2str
    && git clone https://github.com/rtklibexplorer/RTKLIB.git \
    && make --directory=RTKLIB/app/consapp/str2str/gcc \
    && make --directory=RTKLIB/app/consapp/str2str/gcc install \
    && rm -r RTKLIB \
    && apt-get autoremove -y apt-utils build-essential git

#install python package
RUN pip install --upgrade pyserial pynmea2 ntripbrowser pyTelegramBotAPI configparser

#copy pybasevar
COPY pybasevar/* /home/
WORKDIR /home
RUN chmod +x ./run.sh
ENTRYPOINT [ "./run.sh" ]
