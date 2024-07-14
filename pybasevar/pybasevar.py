import serial
import pynmea2
import time
import subprocess
import os
import signal
import telebot
from decimal import *
from ntripbrowser import NtripBrowser
import multiprocessing
from datetime import datetime, timedelta
import config
import configparser
import shutil
import os.path
import logging
import threading

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

logging.getLogger('ntripbrowser').setLevel(logging.WARN)

apiKey = os.environ["APIKEY"]
userId = os.environ["USERID"]

##global variable loops
mp_use1 = "CT"
mount_points_last_updated = None
running = True

## activate .ini
configp = configparser.ConfigParser()

## Param.ini
paramname = "param/param_" + userId + ".ini"

## Create user param file
if os.path.isfile(paramname):
    logging.info("%s already exist", paramname)
else:
    shutil.copy('param.ini', paramname)
    logging.info("Creating %s", paramname)

configp.read(paramname)

def editparam():
    with open(paramname,'w') as configfile:
        configp.write(configfile)

def local_time_to_tuple(local_time):
    if not local_time:
        return None

    t = tuple(int(i) for i in local_time.split(':')[:])

    if len(t) != 3:
        raise Exception(local_time + " is not a valid local time!")

    return t

##Telegram param
configp["telegram"]["api_key"] = apiKey
configp["telegram"]["user_id"] = userId

editparam()

configp.read(paramname)

start_time_tuple = local_time_to_tuple(configp["global"]["start_time"])
stop_time_tuple = local_time_to_tuple(configp["global"]["stop_time"])

def is_working_hours():
    global start_time_tuple
    global stop_time_tuple

    if start_time_tuple is None or stop_time_tuple is None:
        return True

    now = datetime.now()
    current_local_time = (now.hour, now.minute, now.second)

    return current_local_time > start_time_tuple and current_local_time < stop_time_tuple

if start_time_tuple is not None and stop_time_tuple is not None:
    logging.info("Ensure local time is between %s and %s", start_time_tuple, stop_time_tuple)

    while True:
        if is_working_hours():
            logging.info("It's time! Ready to rock!")
            break

        time.sleep(1)

bot = telebot.TeleBot(configp["telegram"]["api_key"])

@bot.message_handler(commands=['restart'])
def send_restart(message):
    configp.read(paramname)
    bot.reply_to(message, "Restarting ... (I'll be back in a few seconds!)")
    # Make it simple and just stop the app, count on docker to restart everything
    # This is better than trying to restart ourself as we may leak resources
    stop_server()

#base filter
@bot.message_handler(commands=['excl'])
def send_exclE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Edit exclude Base(s):\n old value:"+configp["data"]["exc_mp"]+",\n Enter the new value ! ")
    bot.register_next_step_handler(msg, processSetExclE)
def processSetExclE(message):
    answer = message.text
    if answer.isupper():
        logging.info(answer)
        configp["data"]["exc_mp"] = answer
        editparam()
        bot.reply_to(message,"NEW exclude Base(s): "+configp["data"]["exc_mp"])
    else:
        bot.reply_to(message, 'Oooops bad value!')

#hysteresis
@bot.message_handler(commands=['htrs'])
def send_htrsE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Edit Hysteresis:\n old value:"+configp["data"]["htrs"]+"km,\n Enter the new value ! ")
    bot.register_next_step_handler(msg, processSetHtrsE)
def processSetHtrsE(message):
    answer = message.text
    if answer.isdigit():
        logging.info(answer)
        configp["data"]["htrs"] = answer
        editparam()
        bot.reply_to(message,"NEW Hysteresis: "+configp["data"]["htrs"]+"km")
    else:
        bot.reply_to(message, 'Oooops bad value!')

#Critical distance
@bot.message_handler(commands=['crit'])
def send_critE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Edit Maximum distance before GNSS base change:\n Old value:"+configp["data"]["mp_km_crit"]+"km,\n Enter the new value ! ")
    bot.register_next_step_handler(msg, processSetCritE)
def processSetCritE(message):
    answer = message.text
    if answer.isdigit():
        logging.info(answer)
        configp["data"]["mp_km_crit"] = answer
        editparam()
        bot.reply_to(message,"NEW Maximum distance before GNSS base change saved: "+configp["data"]["mp_km_crit"]+"km")
    else:
        bot.reply_to(message, 'Oooops bad value!')

#search distance
@bot.message_handler(commands=['dist'])
def send_distE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Edit Max search distance of GNSS bases saved:\n old value:"+configp["data"]["maxdist"]+"km")
    bot.register_next_step_handler(msg, processSetDistE)
def processSetDistE(message):
    answer = message.text
    if answer.isdigit():
        logging.info(answer)
        configp["data"]["maxdist"] = answer
        editparam()
        bot.reply_to(message,"NEW Max search distance: "+configp["data"]["maxdist"]+"km")
    else:
        bot.reply_to(message, 'Oooops bad value!')

#caster
@bot.message_handler(commands=['caster'])
def send_casterE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Edit caster adress and port:\n old value:\n"+configp["caster"]["adrs"]+":"+configp["caster"]["port"]+"\n Enter caster adress: ")
    bot.register_next_step_handler(msg, processSetCasterE)
def processSetCasterE(message):
    answer = message.text
    if answer.islower():
        logging.info(answer)
        configp["caster"]["adrs"] = answer
        msg = bot.reply_to(message,"NEW caster adresse: "+configp["caster"]["adrs"]+"\nEnter New port:")
        bot.register_next_step_handler(msg, processSetCasterPortE)
    else:
        bot.reply_to(message, 'Oooops bad value!')
def processSetCasterPortE(message):
    answer = message.text
    if answer.isdigit():
        logging.info(answer)
        configp["caster"]["port"] = answer
        editparam()
        bot.reply_to(message,"NEW caster adress + port: "+configp["caster"]["adrs"]+":"+configp["caster"]["port"])
    else:
        bot.reply_to(message, 'Oooops bad value!')

#dowload logs
@bot.message_handler(commands=['log'])
def notas(mensagem):
    mensagemID = mensagem.chat.id
    doc = open(logname, 'rb')
    bot.send_document(mensagemID, doc)

#clear log
@bot.message_handler(commands=['clear'])
def send_logE(message):
    configp.read(paramname)
    msg = bot.reply_to(message,"Do you really want to delete the logs? (Yes/No)")
    bot.register_next_step_handler(msg, processSetLogE)
def processSetLogE(message):
    answer = message.text
    if answer == "Yes":
        logging.info(answer)
        clearlog()
        bot.reply_to(message,"The log file is now empty")
    else:
        bot.reply_to(message, 'Ok, logs kept in state. Bye!')

#show last coordinates / map
@bot.message_handler(commands=['map'])
def send_map(message):
    configp.read(paramname)
    telegramposition()
    telegramlocation()

#principal messsage
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    configp.read(paramname)
    mes=("Connected to Mount Point: \n*"+configp["data"]["mp_use"]+ "*\n" +
    "Last distance between Rover/Base: \n*"+configp["data"]["dist_r2mp"]+" km "+
    configp["coordinates"]["date"]+" "+configp["coordinates"]["time"]+"*"
    + "\n\n" + "Parameters:\n"
    "*/excl* Bases GNSS exclude: \n*"+configp["data"]["exc_mp"]+ "*\n" +
    "*/dist* Max search distance of bases: \n*"+configp["data"]["maxdist"]+"*km"+ "\n" +
    "*/crit* Max distance before base change: \n*"+ configp["data"]["mp_km_crit"] +"*km" + "\n" +
    "*/htrs* Hysteresis: *"+configp["data"]["htrs"]+"*km"+ "\n\n" +
    "*/map* Show last position\n"
    "*/log*    Download change logs\n" +
    "*/clear* Delete logs\n\n"+
    "*/restart* Restart services")
    bot.reply_to(message,mes,parse_mode= 'Markdown')

#Get position and map
def telegramposition():
    configp.read(paramname)
    bot.send_message(configp["telegram"]["user_id"],"Last Rover position: \n"+
        configp["coordinates"]["lat"]+","+
        configp["coordinates"]["lon"]+"\n"+
        configp["coordinates"]["date"]+" "+configp["coordinates"]["time"]+"\n"+
        "Fix quality: "+configp["coordinates"]["type"]+"\n"+
        "HDOP:        "+configp["coordinates"]["hdop"]+"\n"+
        "Altitude:    "+configp["coordinates"]["elv"]+"\n"+
        "ID station:  "+configp["coordinates"]["idsta"]+"\n"+
        "Connected to "+configp["data"]["mp_use"])

def telegramlocation():
    bot.send_location(
        chat_id=configp["telegram"]["user_id"],
        longitude=configp["coordinates"]["lon"],
        latitude=configp["coordinates"]["lat"],
        horizontal_accuracy=configp["coordinates"]["hdop"],
    )

##Create user log file
def createlog():
    global logname
    logname = "logs/basevarlog_"+configp["telegram"]["user_id"]+".csv"
    editparam()
    with open(logname, 'w') as f:
        f.write('action,base,distance,lat,lon,date,quality,hdop,elv,idsta\n')
        f.close

##Save LOG
def savelog(message):
    ##log in file
    file = open(logname, "a")
    file.write(message)
    file.write('\n')
    file.close

#Delete logs
def clearlog():
    os.remove(logname)
    createlog()

def movetobase():
    ## LOG Move to base
    logging.info("------")
    logging.info("CASTER: Move to base %s!", mp_use1)
    logging.info("------")
    ## KILL old str2str_in
    killstr()
    ## Upd variables & Running a new str2str_in service
    configp["data"]["mp_use"] = mp_use1
    editparam()
    time.sleep(2)
    start_in_str2str()
    ##Metadata
    message = ("Move to base," +
    str(mp_use1) +","+
    str(round(mp_use1_km,2))+","+
    configp["coordinates"]["lat"]+","+
    configp["coordinates"]["lon"]+","+
    configp["coordinates"]["date"]+" "+
    configp["coordinates"]["time"]+","+
    configp["coordinates"]["type"]+","+
    configp["coordinates"]["hdop"]+","+
    configp["coordinates"]["elv"]+","+
    configp["coordinates"]["idsta"])
    savelog(message)
    bot.send_message(configp["telegram"]["user_id"], "📡 We are now connected to " + str(mp_use1))
    telegramlocation()
    telegramposition()

def ntripbrowser():
    global browser
    global getmp
    global flt1
    global mp_use1
    global mp_use1_km
    global mp_Carrier
    global mount_points_last_updated

    now = datetime.now()

    if mount_points_last_updated is not None and (now - mount_points_last_updated).seconds < 60:
        return

    mount_points_last_updated = now

    logging.info("ntripbrowser > Looking up mount points")

    ## 2-Get caster sourcetable
    browser = (
        NtripBrowser(
            host=configp["caster"]["adrs"],
            port=configp["caster"]["port"],
            timeout=10,
            coordinates=(Decimal(configp["coordinates"]["lat"]),Decimal(configp["coordinates"]["lon"])),
            maxdist=int(configp["data"]["maxdist"])
        )
    )

    flt = browser.get_mountpoints()['str']

    # Purge list
    flt1 = []
    ## Param base filter
    excl =  list(configp["data"]["exc_mp"].split(" "))
    ## filter carrier L1-L2 & exclude base
    flt1 = [m for m in flt if int(m['Carrier'])>=2 and m['Mountpoint'] not in excl]
    ## GET nearest mountpoint
    for i, value in enumerate(flt1):
        ## Get first row
        if i == 0 :
            ## LOG Nearest base available
            mp_use1 = value["Mountpoint"]
            mp_use1_km = value["Distance"]
            mp_Carrier = value["Carrier"]
            # print(
            #     "INFO: Nearest base is ",mp_use1,
            #     round(mp_use1_km,2),"km; Carrier:",mp_Carrier)
            # print(
            #     "INFO: Distance between Rover & connected base ",
            #     configp["data"]["mp_use"],Decimal(configp["data"]["dist_r2mp"]),"km")

    ## Value on connected base
    flt_r2mp = [m for m in flt if m['Mountpoint']==configp["data"]["mp_use"]]
    ## GET distance between rover and mountpoint used.
    for r in flt_r2mp:
        configp["data"]["dist_r2mp"] = str(round(r["Distance"],2))
        configp["data"]["mp_alive"] = r['Mountpoint']
        editparam()
    ## LOG Watch all nearests mountpoints
    # for i in flt:
    #     mp = i["Mountpoint"]
    #     di = round(i["Distance"],2)
    #     car = i["Carrier"]
    #     print(mp,di,"km; Carrier:", car)

## 03-START loop to check base alive + rover position and nearest base
def loop_mp():
    global running
    global mp_use1
    global mp_use1_km
    global msg

    while running:
        try:
            if not is_working_hours():
                logging.info("loop_mp > Not in working hours anymore, exiting")
                bot.send_message(configp["telegram"]["user_id"], configp["message"]["exit_non_working_hours"])
                stop_server()
                break

            ## Get data from Caster
            ntripbrowser()

            ##My base is Alive?
            flt_basealive = [m for m in flt1 if m['Mountpoint']==configp["data"]["mp_alive"]]
            if len(flt_basealive) == 0:
                logging.info("INFO: Base %s is DEAD!", configp["data"]["mp_alive"])
                movetobase()
                continue

            # print("INFO: Connected to ",configp["data"]["mp_use"],", Waiting for the rover's geographical coordinates......")
            ## 1-Analyse nmea from gnss ntripclient for get lon lat
            line = config.sio.readline()

            if not line:
                logging.info("Received empty line, skipping")
                continue

            logging.debug("Line received: %s", line.replace("\n", ""))

            msg = pynmea2.parse(line)

            ## Exclude bad longitude
            ## This actually happens when client is not connected
            if msg.longitude == 0.0:
                logging.debug("Bad longitude")
                continue

            ## LOG coordinate from Rover
            presentday = datetime.now()
            configp["coordinates"]["lat"] = str(round(msg.latitude,7))
            configp["coordinates"]["lon"] = str(round(msg.longitude,7))
            configp["coordinates"]["date"] = str(presentday.strftime('%Y-%m-%d'))
            configp["coordinates"]["time"] = str(msg.timestamp)
            configp["coordinates"]["type"] = str(msg.gps_qual)
            configp["coordinates"]["hdop"] = str(msg.horizontal_dil)
            configp["coordinates"]["elv"] = str(msg.altitude)
            configp["coordinates"]["idsta"] = str(msg.ref_station_id)
            editparam()

            logging.info("------")
            logging.info(
                "ROVER: (%s, %s) %s",
                str(configp["coordinates"]["lat"]),
                str(configp["coordinates"]["lon"]),
                str(configp["coordinates"]["time"])
            )
            logging.info("------")

            ## 2-Get caster sourcetable
            ntripbrowser()

            ### Check if it is necessary to change the base
            ## nearest Base is different?
            if configp["data"]["mp_use"] != mp_use1:
                ## Check Critical distance before change ?
                if Decimal(configp["data"]["dist_r2mp"]) > int(configp["data"]["mp_km_crit"]):
                    ##critique + Hysteresis(htrs)
                    crithtrs = int(configp["data"]["mp_km_crit"]) + int(configp["data"]["htrs"])
                    if Decimal(configp["data"]["dist_r2mp"]) < crithtrs:
                        logging.info("INFO: Hysteresis critique running: %skm", str(crithtrs))
                    else:
                        ##middle mount point 2 mount point hysteresis
                        r2mphtrs = mp_use1_km + int(configp["data"]["htrs"])
                        if Decimal(configp["data"]["dist_r2mp"]) < r2mphtrs:
                            logging.info("INFO: Hysteresis MP 2 MP running: %skm", str(r2mphtrs))
                        else:
                            movetobase()
                else:
                    logging.info(
                        "%s nearby (%s) but critical distance not reached: %skm",
                        mp_use1,
                        str(Decimal(configp["data"]["dist_r2mp"])),
                        str(configp["data"]["mp_km_crit"])
                    )

            if configp["data"]["mp_use"] == mp_use1:
                logging.info("INFO: Always connected to %s", mp_use1)
        except serial.SerialException:
            logging.exception("Device error")
            time.sleep(1)
            continue
        except pynmea2.ParseError:
            logging.exception("Parse error")
            time.sleep(1)
            continue
        except Exception:
            logging.exception("Exception")
            time.sleep(1)
            continue

def stop_server():
    global running
    ## KILL old str2str_in
    killstr()
    logging.info("stop_server > Stop running")
    running = False
    logging.info("Bot > Stop polling (from stop_server)")
    bot.stop_polling()

def killstr():
    # iterating through each instance of the process
    for line in os.popen("ps ax | grep 'str2str -in ntrip' | grep -v grep"):
        logging.info("We need to kill '%s'", line)
        fields = line.split()
        # extracting Process ID from the output
        pidkill = fields[0]
        # terminating process
        os.kill(int(pidkill), signal.SIGKILL)
    logging.info("KILLING all 'STR2STR -in ntrip' Successfully terminated")

def str2str_out():
    global str2str_out
    ##run ntripcaster
    str2str_out = subprocess.Popen(config.ntripc.split())

def str2str_in():
    global str2str_in
    configp.read(paramname)
    bashstr = config.stream1+configp["data"]["mp_use"]+config.stream2
    str2str_in = subprocess.Popen(bashstr.split())

def start_out_str2str():
    global out_str
    out_str = multiprocessing.Process(name='str_out',target=str2str_out)
    out_str.deamon = True
    logging.info("Out_str Started")
    out_str.start()

def start_in_str2str():
    global in_str
    in_str = multiprocessing.Process(name='str_in',target=str2str_in)
    in_str.deamon = True
    logging.info("In_str Started")
    in_str.start()

if __name__ == '__main__':
    createlog()

    bot.send_message(configp["telegram"]["user_id"], configp["message"]["start1"])
    bot.send_message(configp["telegram"]["user_id"], configp["message"]["start2"])

    start_out_str2str()
    start_in_str2str()

    threading.Thread(target=bot.infinity_polling, name='bot_infinity_polling', daemon=True).start()

    loop_mp()

    logging.info("Exiting")
