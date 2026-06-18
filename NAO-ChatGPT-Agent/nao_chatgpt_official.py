# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║      NAO V5  —  Multimodal AI Integration  —  Standalone Script        ║
║                                                                      ║
║  Usage:                                                                ║
║    python nao_chatgpt.py                                             ║
║    python nao_chatgpt.py --pip 192.168.0.2 --server 192.168.0.8:8080║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import print_function

import sys
import os
import time
import uuid
import threading
import signal
import codecs
import tempfile
import math

#encoder fixes for python 2.7
if sys.version_info[0] == 2:
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout)
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr)

#NAOqi sdk
from naoqi import ALProxy, ALBroker, ALModule

#external dependencies that are not from python2.7
try:
    import requests
except ImportError:
    print(u"[ERROR] install requests: pip install requests")
    sys.exit(1)

try:
    import paramiko
except ImportError:
    print(u"[ERROR] install paramiko: pip install paramiko")
    sys.exit(1)

#ROBO GERENAL SETUO
NAO_IP   = "192.168.0.2", #change this for the IP adress from NAO on your network
NAO_PORT = 9559

#NAO ROBOT CREDENTIALS
NAO_SSH_USER = "nao",
NAO_SSH_PASS = "nao"

#PERSONA
#USE ONLY ASCII CHARACTERES HERE, DO NOT USE ANY ACCENT 
PERSONA = u"Jarvis-um-Assistente-Robotico-de-Inteligencia-Artificial-Inspirado-na-criação-de-Tony-Stark-desenvolvido-pela-Ciencia-da-Computacao-na-PUC-Pocos-de-Caldas"

#autenticação de servidor
SERVER_IP       = "192.168.0.8:8080"
AUTH_TOKEN      = "change-this-auth-token" #ALTERE ESSE AUTH TOKEN PARA O TOKEN VÁLIDO DO MODELO DE AI
RESPONSE_LENGTH = "short"       #tamanho da resposta
AI_VERSION      = "gpt-4o"
ROBOT_LANGUAGE  = "Brazilian" #ALTERE PARA O IDIOMA DESEJADO

#RECORDING TIME
RECORDING_DURATION = 5.0   #in seconds

#POSTURES and speed that the robot will use
POSTURE_SIT       = "Sit"
POSTURE_STAND     = "Stand"
POSTURE_SPEED     = 0.6
MAX_POSTURE_TRIES = 3

LEDS_EYES = "FaceLeds"

#LED collor pallet for the eyes collors on 0xRRGGBB format
LED_AZUL_ROYAL = 0x0055FF   #for presentation / speech
LED_VERDE      = 0x00CC00   #for listening
LED_LARANJA    = 0xFF6600   #when the robot is executing the thinking posture
LED_VERMELHO   = 0xFF0000   #farewell

#paths on NAO robot for storing the data
ROBOT_PHOTO_DIR  = "/home/nao/recordings/cameras/"
ROBOT_PHOTO_PATH = ROBOT_PHOTO_DIR + "image.jpg"
ROBOT_AUDIO_DIR  = "/home/nao/recordings/microphones/"
ROBOT_AUDIO_PATH = ROBOT_AUDIO_DIR + "recording.ogg"

#local path for the beep file
ROBOT_BEEP_PATH  = "/home/nao/sounds/beep.wav"   #copied via SCP for pepper

#local cache on the pc
LOCAL_CACHE_DIR = os.path.join(tempfile.gettempdir(), "nao_cache")

#HEAD tat
HEAD_TOUCH_EVENTS = [
    "FrontTactilTouched",
    "MiddleTactilTouched",
    "RearTactilTouched",
]

#DICTIONARY with LOCALIZED LANGUAGES AVAILABLE FOR NAO ROBOT
ASK_OR_STOP_SENTENCES = {
    "Arabic":     u"  ",
    "Czech":      u" Ahoj ",
    "Danish":     u" Hej ",
    "German":     u" Hallo ",
    "Greek":      u"  ",
    "English":    u" Ask or say no to stop ",
    "Spanish":    u" Hola ",
    "Finnish":    u" Hei ",
    "French":     u" Bonjour ",
    "Italian":    u" Ciao ",
    "Japanese":   u" こんにちは ",
    "Korean":     u" 안녕하세요 ",
    "Dutch":      u" Hallo ",
    "Norwegian":  u"  ",
    "Polish":     u" Cześć ",
    "Brazilian":  u" Pergunte ou diga PARE para encerrar",
    "Portuguese": u" Olá ",
    "Russian":    u" Привет ",
    "Swedish":    u" Hallå ",
    "Turkish":    u" Merhaba ",
    "Chinese":    u"  ",
}

THINKING_SENTENCES = {
    "Arabic":     u"  ",
    "Czech":      u" Ahoj ",
    "Danish":     u" Hej ",
    "German":     u" Hallo ",
    "Greek":      u"  ",
    "English":    u" Hmmm thinking.. ",
    "Spanish":    u" Hola ",
    "Finnish":    u" Hei ",
    "French":     u" Bonjour ",
    "Italian":    u" Ciao ",
    "Japanese":   u" こんにちは ",
    "Korean":     u" 안녕하세요 ",
    "Dutch":      u" Hallo ",
    "Norwegian":  u"  ",
    "Polish":     u" Cześć ",
    "Brazilian":  u" Um momentinho, estou pensando...",
    "Portuguese": u" Olá ",
    "Russian":    u" Привет ",
    "Swedish":    u" Hallå ",
    "Turkish":    u" Merhaba ",
    "Chinese":    u"  ",
}

#UTILITIES
def log(tag, msg):
    ts = time.strftime("%H:%M:%S")
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", errors="replace")
    print(u"[{}] [{}] {}".format(ts, tag, msg))


def ensure_local_dir(directory):
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory)
            log("DIR", u"Created locally: {}".format(directory))
        except OSError as e:
            log("DIR", u"ERROR creating {}: {}".format(directory, e))
            raise


def safe_str(content):
    #converts to unicode under python 2.7 for avoiding UnicodeDecoreError
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def nao_str(text):
    """
    Converts text to the format accepted by NAOqi 2.1.4's ALAnimatedSpeech
    and ALTextToSpeech: str (bytes) encoded in UTF-8.

    No Python 2.7:
      - unicode → encode to str (UTF-8 bytes)
      - str (bytes) → returned as is
      - None or other → converted to empty str

    NAOqi 2.1 does not accept unicode directly in say() —
    it expects str (bytes). Hence the error:
    "Call argument number 0 conversion failure from Value to Unknown"
    """
    if text is None:
        return ""
    if isinstance(text, unicode):
        return text.encode("utf-8")
    if isinstance(text, bytes):
        return text
    return str(text)


#SFTP CLIENT
class RobotSFTP(object):

    def __init__(self, host, user, password, port=22):
        self._host     = host
        self._user     = user
        self._password = password
        self._port     = port
        self._ssh      = None
        self._sftp     = None

    def connect(self):
        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(
                self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                timeout=10,
            )
            self._sftp = self._ssh.open_sftp()
            log("SFTP", u"Connected to robot: {}".format(self._host))
            return True
        except Exception as e:
            log("SFTP", u"ERROR connecting: {}".format(e))
            return False

    def mkdir_robot(self, robot_dir):
        if self._ssh is None:
            self.connect()
        try:
            self._ssh.exec_command("mkdir -p {}".format(robot_dir))
            log("SFTP", u"Directory ensured on robot: {}".format(robot_dir))
        except Exception as e:
            log("SFTP", u"ERROR mkdir: {}".format(e))

    def get_file(self, robot_path, local_path):
        if self._sftp is None:
            if not self.connect():
                return False
        try:
            self._sftp.get(robot_path, local_path)
            log("SFTP", u"OK: {} -> {}".format(robot_path, local_path))
            return True
        except Exception as e:
            log("SFTP", u"ERROR downloading {}: {}".format(robot_path, e))
            try:
                self.connect()
                self._sftp.get(robot_path, local_path)
                log("SFTP", u"OK after reconnection: {}".format(robot_path))
                return True
            except Exception as e2:
                log("SFTP", u"Final ERROR: {}".format(e2))
                return False

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
            if self._ssh:
                self._ssh.close()
        except Exception:
            pass

nao_mod = None
#MAIN MODULE
class NaoChatGPT(ALModule):

    _instance = None

    def __init__(self, name):
        ALModule.__init__(self, name)
        NaoChatGPT._instance = self
        self._running        = True

        #al the NAOqi modules that are used on application
        self.memory       = ALProxy("ALMemory")
        self.tts          = ALProxy("ALTextToSpeech")
        self.atts         = ALProxy("ALAnimatedSpeech")
        self.posture      = ALProxy("ALRobotPosture")
        self.motion       = ALProxy("ALMotion")        
        self.audio_dev    = ALProxy("ALAudioDevice")
        self.audio_player = ALProxy("ALAudioPlayer")
        self.photo        = ALProxy("ALPhotoCapture")
        self.leds         = ALProxy("ALLeds")

        log("INIT", u"NAOqi proxies created")

        self._twinkle_active = False
        self._twinkle_thread = None
        self._touch_event    = threading.Event()

        self._sftp = RobotSFTP(NAO_IP, NAO_SSH_USER, NAO_SSH_PASS)
        self._sftp.connect()
        self._sftp.mkdir_robot(ROBOT_PHOTO_DIR)
        self._sftp.mkdir_robot(ROBOT_AUDIO_DIR)

        ensure_local_dir(LOCAL_CACHE_DIR)

    #phase 1, setting up persona
    def box_set_persona(self, p):
        log("SET_PERSONA", u"Persona={}".format(p))

        chatId = ""
        try:
            chatId = self.memory.getData("chat-id")
        except Exception:
            log("SET_PERSONA", u"no chat-id found")
        finally:
            if chatId != "" and chatId is not None:
                self.memory.removeData("chat-id")

        persona = ""
        try:
            persona = self.memory.getData("persona")
        except Exception:
            log("SET_PERSONA", u"no persona found")
        finally:
            if persona != "" and persona is not None:
                self.memory.removeData("persona")

        log("SET_PERSONA", u"guild={}".format(str(uuid.uuid4())))

        #ensure ASCII for the URL, replace spaces with hyphens
        if isinstance(p, unicode):
            personaToSave = p.replace(u" ", u"-")
        else:
            personaToSave = p.decode("utf-8", errors="replace").replace(u" ", u"-")

        log("SET_PERSONA", u"personaToSave={}".format(personaToSave))

        self.memory.insertData("chat-id", str(uuid.uuid4()))
        self.memory.insertData("persona", personaToSave)

    #phase 1 of setting the server
    def box_set_server(self, p):
        serverIP = ""
        try:
            serverIP = self.memory.getData("server-ip")
        except Exception:
            log("SET_SERVER", u"no server-ip found")
        finally:
            if serverIP != "" and serverIP is not None:
                self.memory.removeData("server-ip")

        log("SET_SERVER", u"serverIP={}".format(p))
        self.memory.insertData("server-ip", p)
        log("SET_SERVER", u"persisted={}".format(p))

    #phase 1 of setting up a response lenght
    def box_set_response_length(self, p):
        valid = ["short", "medium", "standard"]
        if str(p).lower() not in valid:
            self.atts.say(nao_str(
                u"por favor escolha um comprimento de resposta padrao, "
                u"pode ser curto, medio ou longo"
            ))
            log("SET_RESP_LEN", u"INVALID — aborting")
            self._running = False
            return False

        responseLength = ""
        try:
            responseLength = self.memory.getData("responseLength")
        except Exception:
            log("SET_RESP_LEN", u"no responseLength found")
        finally:
            if responseLength != "" and responseLength is not None:
                self.memory.removeData("responseLength")

        log("SET_RESP_LEN", u"responseLength={}".format(p))
        self.memory.insertData("responseLength", str(p).lower())
        self.memory.insertData("ai-version", AI_VERSION)
        return True

    #phase 2 for sitting the robot down
    def box_sit_down(self):
        log("SIT_DOWN", u"goToPosture({}, {})".format(POSTURE_SIT, POSTURE_SPEED))
        try:
            result = self.posture.goToPosture(POSTURE_SIT, POSTURE_SPEED)
            log("SIT_DOWN", u"success" if result else u"failure")
        except Exception as e:
            log("SIT_DOWN", u"ERROR: {}".format(e))

    #phase 2 with the robot waiting for the head taticle touch
    def box_wait_for_head_touch(self):
        log("TACTILE", u"Robot seated — waiting for head touch...")
        self._touch_event.clear()

        for event_name in HEAD_TOUCH_EVENTS:
            try:
                self.memory.subscribeToEvent(
                    event_name, "NaoChatGPT", "onHeadTouched",
                )
                log("TACTILE", u"Subscribed: {}".format(event_name))
            except Exception as e:
                log("TACTILE", u"Error subscribing {}: {}".format(event_name, e))

        self._touch_event.wait()
        log("TACTILE", u"Touch detected! Continuing...")

    def onHeadTouched(self, event_name, value, subscriber_id):
        log("TACTILE", u"Event={} | Value={}".format(event_name, value))
        if value > 0:
            for ev in HEAD_TOUCH_EVENTS:
                try:
                    self.memory.unsubscribeToEvent(ev, "NaoChatGPT")
                except Exception:
                    pass
            self._touch_event.set()

    #phase 3 taking picture
    def box_take_picture(self):
        log("TAKE_PICTURE", u"Capturing photo...")
        try:
            self.photo.setResolution(2)
            self.photo.setCameraID(0)
            self.photo.setPictureFormat("jpg")
            self.photo.takePicture(ROBOT_PHOTO_DIR, "image")
            log("TAKE_PICTURE", u"Photo saved on robot: {}".format(ROBOT_PHOTO_PATH))
        except Exception as e:
            log("TAKE_PICTURE", u"ERROR capturing: {}".format(e))
            return

        local_photo = os.path.join(LOCAL_CACHE_DIR, "image.jpg")
        ok = self._sftp.get_file(ROBOT_PHOTO_PATH, local_photo)
        if not ok:
            log("TAKE_PICTURE", u"Failed to download photo")

    #phase 3, standing the robot up
    def box_stand_up(self):
        log("STAND_UP", u"goToPosture({}, {})".format(POSTURE_STAND, POSTURE_SPEED))
        try:
            self.posture.setMaxTryNumber(MAX_POSTURE_TRIES)
            result = self.posture.goToPosture(POSTURE_STAND, POSTURE_SPEED)
            log("STAND_UP", u"success" if result else u"failure")
        except Exception as e:
            log("STAND_UP", u"ERROR: {}".format(e))

    #phase 3, robot waving 
    def _aceno_braco_direito(self, cor_led):
        #tested wave sequence used by hello and farewell

        #joints used for the farewell
        joints = ["RShoulderPitch","RShoulderRoll","RElbowYaw","RElbowRoll","RWristYaw"]

        self.leds.fadeRGB(LEDS_EYES, cor_led, 0.3)
        self.motion.setStiffnesses("RArm", 1.0)
        self.motion.closeHand("RHand")

        #initial rest
        self.motion.angleInterpolationWithSpeed(
            joints,
            [math.radians(93), math.radians(-1), math.radians(104), math.radians(2), math.radians(-78)],
            0.5)

        #raising roll and openning the robots hand here
        self.motion.angleInterpolationWithSpeed(
            joints,
            [math.radians(41), math.radians(-5), math.radians(19), math.radians(68), math.radians(11)],
            0.5)
        self.motion.openHand("RHand")

        #elbow bent
        self.motion.angleInterpolationWithSpeed(
            joints,
            [math.radians(22), math.radians(-34), math.radians(53), math.radians(62), math.radians(-30)],
            0.5)

        #arm raised
        self.motion.angleInterpolationWithSpeed(
            joints,
            [math.radians(-60), math.radians(-62), math.radians(33), math.radians(30), math.radians(23)],
            0.6)

        #waving from positions A to B 5 times
        pos_a = [math.radians(-60), math.radians(-59), math.radians(14), math.radians(51), math.radians(24)]
        pos_b = [math.radians(-61), math.radians(-22), math.radians(28), math.radians(53), math.radians(22)]
        for _ in range(5):
            self.motion.angleInterpolationWithSpeed(joints, pos_a, 0.5)
            self.motion.angleInterpolationWithSpeed(joints, pos_b, 0.5)

        #lowering, close the hand simultaneously
        self.motion.post.angleInterpolationWithSpeed(
            joints,
            [math.radians(44), math.radians(-12), math.radians(19), math.radians(71), math.radians(7)],
            0.5)
        self.motion.closeHand("RHand")

        #final rest
        self.motion.angleInterpolationWithSpeed(
            joints,
            [math.radians(85), math.radians(-4), math.radians(3), math.radians(2), math.radians(7)],
            0.5)

        self.leds.fadeRGB(LEDS_EYES, cor_led, 0.5)
        self.motion.setStiffnesses("RArm", 0.0)

    def box_hello_leds(self):
        log("HELLO_LEDS", u"Starting wave + LEDs")
        try:
            self._aceno_braco_direito(LED_AZUL_ROYAL)
            log("HELLO_LEDS", u"success")
        except Exception as e:
            log("HELLO_LEDS", u"ERROR: {}".format(e))

    #phase 3, starting chat
    def box_start_chat(self):
        persona = ""
        try:
            
            persona = self.memory.getData("persona")
            if persona is None:
                persona = ""
            
            #ensurepersona is str (bytes), not unicode
            if isinstance(persona, unicode):
                persona = persona.encode("utf-8")
        except Exception:
            log("START_CHAT", u"no persona found")

        #BRAZILIAN greeting without accents for correct pronnuncing
        greeting = (
            "Seja bem vindo. Que bom te ver por aqui. Eu sou "
            + persona
            + ". Por favor pergunte apos o BIP"
            + ". Irei avisar enquanto estiver pensando."
        )

        log("START_CHAT", u"Speaking greeting...")

        #blue eyes during the presentation
        try:
            self.leds.fadeRGB(LEDS_EYES, LED_AZUL_ROYAL, 0.3)
        except Exception:
            pass

        #enable body language while speaking
        #setBodyLanguageEnabled(True) enables the automatic gestures
        try:
            self.atts.setBodyLanguageEnabled(True)
        except Exception:
            pass

        #speak with gestures via ALAnimatedSpeech
        #ese atts.say() with contextual bodyLanguageMode to gesture
        try:
            self.atts.say(
                greeting,
                {"bodyLanguageMode": "contextual",
                 "disableArmsAnimations": False,
                 "disableBodyAnimations": False,
                 "disableHeadAnimations": False,
                 "useArmAndHandMovement": True}
            )
        except Exception:
            #fallback to simple tts if atts fails
            try:
                self.tts.say(greeting)
            except Exception as e:
                log("START_CHAT", u"ERROR in tts.say: {}".format(e))

    #loop instruction
    def box_say_ask_or_stop(self):
        lang = self._get_language()
        text = ASK_OR_STOP_SENTENCES.get(lang, ASK_OR_STOP_SENTENCES["Brazilian"])
        log("ASK_OR_STOP", u"[{}] {}".format(lang, text))
        self._say_text(text)

    #LOOP BEEP trying 3 beep options
    def box_play_beep(self):
        log("BEEP", u"Playing beep...")

        #green eyes while the robot is listening
        try:
            self.leds.fadeRGB(LEDS_EYES, LED_VERDE, 0.3)
        except Exception:
            pass

        #list of paths to try in order
        beep_paths = [
            ROBOT_BEEP_PATH,
            "/home/nao/sounds/beep.wav",
            "/home/nao/sounds/beep_pepper.wav",
            "/home/nao/escutando.wav",
            "/home/nao/listen.wav",
        ]

        played = False
        for path in beep_paths:
            try:
                fid = self.audio_player.post.playFileFromPosition(
                    path, 0, 0.8, 0.0
                )
                self.audio_player.wait(fid, 0)
                log("BEEP", u"Played: {}".format(path))
                played = True
                break
            except Exception:
                continue

        if not played:

            #fallback generate beep via TTS with a high tone
            log("BEEP", u"No WAV file available — using TTS fallback")
            try:
                self.tts.say(nao_str(u"\\vct=200\\ \\rspd=400\\ Bip \\rst\\"))
            except Exception as e:
                log("BEEP", u"ERROR in TTS fallback: {}".format(e))

    #loop record voice
    def box_record_voice(self):
        log("VOICE", u"Recording: {}".format(ROBOT_AUDIO_PATH))
        log("VOICE", u"Duration: {} s".format(RECORDING_DURATION))

        try:
            self.audio_dev.startMicrophonesRecording(ROBOT_AUDIO_PATH)
            time.sleep(RECORDING_DURATION)
            self.audio_dev.stopMicrophonesRecording()
            log("VOICE", u"Recording finished")
        
        except Exception as e:
            log("VOICE", u"ERROR: {}".format(e))
            try:
                self.audio_dev.stopMicrophonesRecording()
            except Exception:
                pass
            return

        local_audio = os.path.join(LOCAL_CACHE_DIR, "recording.ogg")
        ok = self._sftp.get_file(ROBOT_AUDIO_PATH, local_audio)
        if not ok:
            log("VOICE", u"Failed to download audio")

    #loop twinkle
    def box_twinkle_start(self):
        self._twinkle_active = True
        self._twinkle_thread = threading.Thread(target=self._twinkle_loop)
        self._twinkle_thread.daemon = True
        self._twinkle_thread.start()
        log("TWINKLE", u"Animation started")

        #orange eyes while robot's thinking 
        try:
            self.leds.fadeRGB(LEDS_EYES, LED_LARANJA, 0.3)
        except Exception:
            pass

        #Speak BEFORE moving the arm
        try:
            self.tts.say("Um momentinho, estou pensando.")
        except Exception:
            pass

        #left arm to the head (position measured with sensor)
        try:
            self.motion.setStiffnesses("LArm", 1.0)

            joints_L = [
                "LShoulderPitch",
                "LShoulderRoll",
                "LElbowYaw",
                "LElbowRoll",
                "LWristYaw",
            ]

            pos_cabeca_L = [
                math.radians(-51.42),
                math.radians(28.47),
                math.radians(-54.76),
                math.radians(-88.50),
                math.radians(-60.30),
            ]

            self.motion.closeHand("LHand")
            self.motion.angleInterpolationWithSpeed(joints_L, pos_cabeca_L, 0.5)

            for _ in range(2):
                self.motion.openHand("LHand")
                time.sleep(0.3)
                self.motion.closeHand("LHand")
                time.sleep(0.3)

        except Exception as e:
            log("TWINKLE", u"ERROR in thinking gesture: {}".format(e))

    def box_twinkle_stop(self):
        self._twinkle_active = False
        if self._twinkle_thread:
            self._twinkle_thread.join(timeout=2.0)

        #returning the arm for a neutral posicion
        try:
            joint_names_L = [
                "LShoulderPitch",
                "LShoulderRoll",
                "LElbowYaw",
                "LElbowRoll",
                "LWristYaw",
            ]
            pos_neutro_L = [
                math.radians(75),    #shoulder down
                math.radians(5),     #arm close to the body
                math.radians(-70),   #elbow neutral
                math.radians(-5),    #elbow almost straight
                math.radians(0),     #wrist neutral
            ]
            self.motion.angleInterpolationWithSpeed(
                joint_names_L, pos_neutro_L, 0.4
            )
            self.motion.closeHand("LHand")
            self.motion.setStiffnesses("LArm", 0.0)  #relaxing the arm
        except Exception as e:
            log("TWINKLE", u"ERROR returning arm: {}".format(e))

        try:
            self.leds.fade(LEDS_EYES, 0.5, 0.3)
        except Exception:
            pass
        log("TWINKLE", u"Animation finished")

    def _twinkle_loop(self):
        try:
            while self._twinkle_active:
                self.leds.fade(LEDS_EYES, 1.0, 0.4)
                time.sleep(0.5)
                if not self._twinkle_active:
                    break
                self.leds.fade(LEDS_EYES, 0.0, 0.4)
                time.sleep(0.5)
                if not self._twinkle_active:
                    break
                self.leds.fade(LEDS_EYES, 0.8, 0.1)
                time.sleep(0.2)
        except Exception as e:
            log("TWINKLE_LOOP", u"ERROR: {}".format(e))

    def box_say_thinking(self):
        lang = self._get_language()
        text = THINKING_SENTENCES.get(lang, THINKING_SENTENCES["Brazilian"])
        log("THINKING", u"[{}] {}".format(lang, text))
        self._say_text(text)

    #LOOP CHATGPT
    def box_chatgpt_call(self):
        log("CHATGPT", u"Starting API call")

        try:
            result         = self.memory.getData("chat-id")
            serverIP       = self.memory.getData("server-ip")
            persona        = self.memory.getData("persona")
            responseLength = self.memory.getData("responseLength")
            aiVersion      = self.memory.getData("ai-version")
        except Exception as e:
            log("CHATGPT", u"ERROR reading ALMemory: {}".format(e))
            return ""

        # Ensure no value is None before concatenating into the URL
        if not serverIP:
            log("CHATGPT", u"Server IP not found, aborting.")
            return ""
        if not result:
            log("CHATGPT", u"chat-id not found, aborting.")
            return ""
        if not persona:
            #fallback uses the global persona configured in the script instead of aborting, ALMemory may have had a timing
            
            if isinstance(PERSONA, unicode):
                persona = PERSONA.encode("utf-8")
            else:
                persona = PERSONA
            log("CHATGPT", u"persona missing in ALMemory — using fallback: {}".format(persona))
        if not responseLength:
            log("CHATGPT", u"responseLength not found, aborting.")
            return ""
        if not aiVersion:
            #safe fallback
            aiVersion = AI_VERSION
            self.memory.insertData("ai-version", aiVersion)
            log("CHATGPT", u"aiVersion missing — using fallback: {}".format(aiVersion))

        api_url = (
            "http://" + serverIP
            + "/speech/id/" + result
            + "/culture/pt-br/raw/false/persona/" + persona
            + "/responselength/" + responseLength
            + "/ai-version/" + aiVersion
        )
        log("CHATGPT", u"URL = {}".format(api_url))

        local_photo = os.path.join(LOCAL_CACHE_DIR, "image.jpg")
        local_audio = os.path.join(LOCAL_CACHE_DIR, "recording.ogg")

        files = {}
        try:
            with open(local_photo, "rb") as f:
                files["photo"] = ("image.jpg", f.read(), "image/jpeg")
            log("CHATGPT", u"Photo included: {} bytes".format(len(files["photo"][1])))
        except Exception:
            log("CHATGPT", u"Photo file not found, skipping.")

        try:
            with open(local_audio, "rb") as f:
                files["audio"] = ("recording.ogg", f.read(), "audio/ogg")
            log("CHATGPT", u"Audio included: {} bytes".format(len(files["audio"][1])))
        except Exception:
            log("CHATGPT", u"Audio file not found, skipping.")

        if not files:
            log("CHATGPT", u"No files found to upload, aborting.")
            return ""

        headers = {"Authorization": AUTH_TOKEN}
        try:
            response = requests.post(api_url, headers=headers, files=files,
                                     timeout=90)
        except requests.exceptions.Timeout:
            log("CHATGPT", u"TIMEOUT")
            return ""
        except requests.exceptions.ConnectionError as e:
            log("CHATGPT", u"Connection ERROR: {}".format(e))
            return ""
        except Exception as e:
            log("CHATGPT", u"ERROR: {}".format(e))
            return ""

        log("CHATGPT", u"Status: {}".format(response.status_code))

        if response.status_code == 200:
            content = response.content

            content_preview = safe_str(content)[:100]
            log("CHATGPT", u"Response: {}".format(content_preview))

            if content in (b"STOP", "STOP"):
                return "STOP"
            elif content in (b"", ""):
                return ""
            elif content not in (b"skip", "skip"):
                
                #decode and speaking with body movements
                content = safe_str(content)
                self.atts.say(
                    nao_str(content),
                    {
                        "bodyLanguageMode":      "contextual",
                        "disableArmsAnimations": False,
                        "disableBodyAnimations": False,
                        "disableHeadAnimations": False,
                        "useArmAndHandMovement": True,
                    }
                )
                return content
            else:
                return "skip"
        else:
            log("CHATGPT", u"Failed. Status: {}".format(response.status_code))
            return ""

    #SWITCH CASE FINAL
    def box_switch_continue_or_stop(self, p):
        try:
            pf = float(p)
            pi = int(pf)
            p  = pi if pf == pi else pf
        except Exception:
            p = str(p)

        p_upper = str(p).upper()
        log("SWITCH", u"Evaluating: '{}'".format(p_upper))

        #CHANGE THOSE WORDS TO STOP ON THE DESIRED LANGUAGE
        stop_words = {"NO", "NAO", u"NÃO", "PARE", "PARAR",
                      "ENCERRAR", "TCHAU", u"ATÉ MAIS",
                      "DESLIGAR", "DESLIGUE"}

        if p_upper in stop_words:
            log("SWITCH", u"END")
            return False
        else:
            log("SWITCH", u"CONTINUE")
            return True

    #HELPERS
    def _get_language(self):
        try:
            return self.tts.getLanguage()
        except Exception:
            return "Brazilian"

    def _say_text(self, text, speed=100, voice_shaping=100):
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        sentence  = u"\\RSPD={}\\  ".format(speed)
        sentence += u"\\VCT={}\\  ".format(voice_shaping)
        sentence += text
        sentence += u"  \\RST\\ "
        try:
            fid = self.tts.post.say(nao_str(sentence))
            self.tts.wait(fid, 0)
        except Exception as e:
            log("SAY_TEXT", u"ERROR: {}".format(e))

    def box_farewell(self):
        #farewell, same as hello but with red LEDs
    
        log("FAREWELL", u"Starting farewell")
        try:
            self.tts.say("Tchauzinho. Estou aqui caso precisar de mim.")
            self._aceno_braco_direito(LED_VERMELHO)
            log("FAREWELL", u"success")
        except Exception as e:
            log("FAREWELL", u"ERROR: {}".format(e))

    def cleanup(self):
        log("CLEANUP", u"Cleaning up resources...")
        self._twinkle_active = False
        for ev in HEAD_TOUCH_EVENTS:
            try:
                self.memory.unsubscribeToEvent(ev, "NaoChatGPT")
            except Exception:
                pass
        try:
            self.leds.fade(LEDS_EYES, 0.5, 0.5)
        except Exception:
            pass
        try:
            self.audio_dev.stopMicrophonesRecording()
        except Exception:
            pass
        try:
            self._sftp.close()
        except Exception:
            pass
        log("CLEANUP", u"Done")

#SCRIPT ORCHESTRATOR
def run_behavior(nao):
    log("MAIN", u"=" * 54)
    log("MAIN", u"NAO V5 <-> Multimodal AI — starting")
    log("MAIN", u"=" * 54)

    #phase 1
    log("MAIN", u"PHASE 1: Configuration")
    nao.box_set_persona(PERSONA)
    nao.box_set_server(SERVER_IP)
    ok = nao.box_set_response_length(RESPONSE_LENGTH)
    if not ok:
        log("MAIN", u"Invalid configuration, exiting")
        return

    #phase
    log("MAIN", u"PHASE 2: Sitting and waiting for touch")
    nao.box_sit_down()
    nao.box_wait_for_head_touch()

    if not nao._running:
        log("MAIN", u"Stopped during wait")
        return

    #phase 3, robot wakes up and introduce itself
    log("MAIN", u"PHASE 3: Waking up")
    nao.box_take_picture()
    nao.box_stand_up()
    nao.box_hello_leds()       #wave + LEDs
    nao.box_start_chat()       #spoken greeting

    #phase 4
    log("MAIN", u"PHASE 4: Conversation loop")
    loop_count = 0
    keep_going = True

    while keep_going and nao._running:
        loop_count += 1
        log("MAIN", u"ITERATION {} ".format(loop_count))

        nao.box_say_ask_or_stop()
        nao.box_play_beep()
        nao.box_record_voice()
        nao.box_take_picture()
        nao.box_twinkle_start()
        nao.box_say_thinking()
        content = nao.box_chatgpt_call()
        nao.box_twinkle_stop()

        log("MAIN", u"Content: '{}'".format(safe_str(content)[:60]))

        if content == "STOP":
            log("MAIN", u"STOP — exiting")
            keep_going = False
            try:
                nao.box_farewell()
            except Exception:
                pass
        elif content == "":

            log("MAIN", u"Empty response: exiting")
            keep_going = False
        
        elif content == "skip":
            log("MAIN", u"SKIP: continuing")
        
        else:
            keep_going = nao.box_switch_continue_or_stop("yes")

    log("MAIN", u"Loop ended after {} iterations".format(loop_count))
    nao.cleanup()


#ENTRY POINT
def main():
    from optparse import OptionParser
    global PERSONA, SERVER_IP, RESPONSE_LENGTH, NAO_IP

    parser = OptionParser()
    parser.add_option("--pip",     dest="pip",     default=NAO_IP)
    parser.add_option("--pport",   dest="pport",   type="int", default=NAO_PORT)
    parser.add_option("--server",  dest="server",  default=None)
    parser.add_option("--length",  dest="length",  default=None)
    parser.add_option("--persona", dest="persona", default=None)

    (opts, _) = parser.parse_args()

    pip    = opts.pip
    pport  = opts.pport
    NAO_IP = pip

    if opts.server  is not None: SERVER_IP       = opts.server
    if opts.length  is not None: RESPONSE_LENGTH = opts.length
    if opts.persona is not None:
    
        #avoiding UnicodeDecodeError in print and URL
        raw = opts.persona
        if isinstance(raw, bytes):
            PERSONA = raw.decode("utf-8", errors="replace")
        else:
            PERSONA = raw

    print(u"")
    print(u"╔══════════════════════════════════════════╗")
    print(u"║  NAO V5 with Multimodal AI — Standalone  ║")
    print(u"╚══════════════════════════════════════════╝")
    print(u"  Robot:    {}:{}".format(pip, pport))
    print(u"  Server:   {}".format(SERVER_IP))
    print(u"  Response: {}".format(RESPONSE_LENGTH))
    
    #print persona with safe encoding for non-UTF-8 terminals
    persona_display = PERSONA if isinstance(PERSONA, unicode) else PERSONA.decode("utf-8", "replace")
    print(u"  Persona:  {}".format(persona_display))
    print(u"  Cache:    {}".format(LOCAL_CACHE_DIR))
    print(u"")

    try:
        broker = ALBroker("NaoChatGPTBroker", "0.0.0.0", 0, pip, pport)
    
    except Exception as e:
        print(u"[ERROR] Could not connect to robot: {}".format(e))
        sys.exit(1)

    print(u"Broker connected: {}:{}".format(pip, pport))

    global nao_mod
    try:
        nao_mod = NaoChatGPT("NaoChatGPT")
    
    except Exception as e:
        print(u"[ERROR] Failed to instantiate NaoChatGPT: {}".format(e))
        broker.shutdown()
        sys.exit(1)

    import sys as _sys
    _sys.modules["__main__"].NaoChatGPT = nao_mod

    try:
        nao_mod.tts.setLanguage(ROBOT_LANGUAGE)
        print(u"Language: {}".format(ROBOT_LANGUAGE))
    except Exception as e:
        print(u"[WARNING] Language not configured: {}".format(e))

    def _signal_handler(sig, frame):
        print(u"\nCtrl+C -> exiting...")
        if NaoChatGPT._instance:
            NaoChatGPT._instance._running = False
            NaoChatGPT._instance._touch_event.set()
            NaoChatGPT._instance.cleanup()
        broker.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        run_behavior(nao_mod)
    except Exception as e:
        print(u"[ERROR] Unhandled exception: {}".format(e))
        import traceback
        traceback.print_exc()
    finally:
        nao_mod.cleanup()
        broker.shutdown()
        print(u"[END] Script terminated.")


if __name__ == "__main__":
    main()