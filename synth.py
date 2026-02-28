#!/usr/bin/env python3
import math
import ctypes

# local PySDL2 folder
from pysdl import *
from pysdl.sdlttf import *


SAMPLE_RATE = 48000
BLOCK_SIZE = 512
MASTER_VOL = 0.2

ATTACK_TIME = 0.05
DECAY_TIME = 0.05
RELEASE_TIME = 0.5
CUTOFF_HZ = 1200.0  # Low-pass filter cutoff

OP_PLAY = 1
OP_MOD = 2
OP_SHIFT = 3
OP_QUIT = 4

MOD_NONE = 0
MOD_MIN_MAJ = 1
MOD_5 = 2
MOD_7 = 3
MOD_SUS4 = 4

KEY_MAP = {
    SDL_SCANCODE_POWER: (OP_QUIT, ),
    SDL_SCANCODE_ESCAPE: (OP_QUIT, ),

    SDL_SCANCODE_L: (OP_SHIFT, -12), # L1
    SDL_SCANCODE_R: (OP_SHIFT, 12), # R1
    SDL_SCANCODE_M: (OP_SHIFT, -1), # L2
    SDL_SCANCODE_S: (OP_SHIFT, 1), # R2

    SDL_SCANCODE_UP: (OP_MOD, MOD_MIN_MAJ),
    SDL_SCANCODE_DOWN: (OP_MOD, MOD_SUS4),
    SDL_SCANCODE_LEFT: (OP_MOD, MOD_5),
    SDL_SCANCODE_RIGHT: (OP_MOD, MOD_7),

    SDL_SCANCODE_1: (OP_PLAY, 1),
    SDL_SCANCODE_2: (OP_PLAY, 2),
    SDL_SCANCODE_3: (OP_PLAY, 3),
    SDL_SCANCODE_4: (OP_PLAY, 4),
    SDL_SCANCODE_5: (OP_PLAY, 5),
    SDL_SCANCODE_6: (OP_PLAY, 6),
    SDL_SCANCODE_7: (OP_PLAY, 7),

    SDL_SCANCODE_SPACE: (OP_PLAY, 1),  # SELECT
    SDL_SCANCODE_RETURN: (OP_PLAY, 2),  # START
    SDL_SCANCODE_B: (OP_PLAY, 3),
    SDL_SCANCODE_Y: (OP_PLAY, 4),
    SDL_SCANCODE_X: (OP_PLAY, 5),
    SDL_SCANCODE_A: (OP_PLAY, 6),
    SDL_SCANCODE_H: (OP_PLAY, 7),
}

SCALE = [None, 0, 2, 4, 5, 7, 9, 11]  # major scale

CHORDS = {
    MOD_NONE: [[], [4, 7], [3, 7], [3, 7], [4, 7], [4, 7], [3, 7], [3, 6]],
    MOD_MIN_MAJ: [[], [3, 7], [4, 7], [4, 7], [3, 7], [3, 7], [4, 7], [4, 7]],
    MOD_5: [[], [7], [7], [7], [7], [7], [7], [7]],
    MOD_7: [[], [4, 7, 11], [3, 7, 11], [3, 7, 11], [4, 7, 11], [4, 7, 11], [3, 7, 11], [3, 6, 11]],
    MOD_SUS4: [[], [5, 7], [5, 7], [5, 7], [5, 7], [5, 7], [5, 7], [5, 7]],
}

ROOT_NAMES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]
CHORD_NAMES = {
    "4+7": "",
    "3+7": "m",
    "3+6": "dim",
    "7": "5",
    "4+7+11": "7",
    "3+7+11": "m7",
    "3+6+11": "m7b5",
    "5+7": "sus4",
}

FONT_PATHS = [
    b"DejaVuSans.ttf",
    b"/usr/share/fonts/dejavu/DejaVuSans.ttf",
    b"/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
]

ENV_OFF = 0
ENV_ATTACK = 1
ENV_DECAY = 2
ENV_SUSTAIN = 3
ENV_RELEASE = 4

TWOPI = 2.0 * math.pi


class Oscillator:

    def __init__(self, pitch: int):

        frequency = 440.0 * 2 ** (pitch / 12)
        self.delta = TWOPI * frequency / SAMPLE_RATE
        self.volume = 0.0
        self.phase = 0.0

        self.env_state = ENV_OFF
        self.level = 0.0

        self.lpf_state = 0.0  # Memory for the one-pole filter

        self.attack_delta = 1 / (ATTACK_TIME * SAMPLE_RATE)
        self.decay_delta = 1 / (DECAY_TIME * SAMPLE_RATE)
        self.release_delta = 1 / (RELEASE_TIME * SAMPLE_RATE)

        # Filter coefficient alpha
        self.lpf_alpha = (TWOPI * CUTOFF_HZ / SAMPLE_RATE) / (TWOPI * CUTOFF_HZ / SAMPLE_RATE + 1.0)

    def attack(self, volume):

        self.volume = volume
        if self.level > volume:
            self.env_state = ENV_DECAY
        else:
            self.env_state = ENV_ATTACK

    def release(self):

        self.env_state = ENV_RELEASE

    def sample(self) -> float:
    
        # Sawtooth formula: 2 * (phase / 2pi) - 1
        sample = 2.0 * (self.phase / TWOPI) - 1.0
        self.phase = (self.phase + self.delta) % TWOPI

        if self.env_state == ENV_ATTACK:
            self.level += self.attack_delta
            if self.level >= self.volume:
                self.level = self.volume
                self.env_state = ENV_SUSTAIN

        elif self.env_state == ENV_DECAY:
            self.level -= self.decay_delta
            if self.level <= self.volume:
                self.level = self.volume
                self.env_state = ENV_SUSTAIN

        elif self.env_state == ENV_RELEASE:
            self.level -= self.release_delta
            if self.level <= 0.0:
                self.level = 0.0
                self.env_state = ENV_OFF

        sample *= self.level

        # Low-Pass One-Pole
        self.lpf_state += (sample - self.lpf_state) * self.lpf_alpha
        return self.lpf_state


class Synth:

    def __init__(self):

        self.chord_name = "-"
        self.oscs: dict[int, Oscillator] = {}

    def change_chord(self, key: int, degree: int, mod: int):

        root = key + SCALE[degree]
        chord = CHORDS[mod][degree]
        pitches = [root + i for i in (0, *chord)]
        
        for pitch, osc in self.oscs.items():
            if pitch not in pitches:
                osc.release()

        for n, pitch in enumerate(pitches):
            osc = self.oscs.get(pitch)
            if osc is None:
                osc = Oscillator(pitch)
                self.oscs[pitch] = osc
            osc.attack(0.8 ** (n + 1))

        chord_code = "+".join(str(i) for i in chord)
        self.chord_name = ROOT_NAMES[root % 12] + CHORD_NAMES[chord_code]

    def release(self):

        for osc in self.oscs.values():
            osc.release()

    def audio_callback(self, userdata, stream, length):

        out_ptr = ctypes.cast(stream, ctypes.POINTER(ctypes.c_float))
        for n in range(length // 4):
            level = sum(o.sample() for o in self.oscs.values())
            out_ptr[n] = level * MASTER_VOL

        pitches = list(self.oscs)
        for pitch in pitches:
            if self.oscs[pitch].env_state == ENV_OFF:
                del self.oscs[pitch]


SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO)
TTF_Init()

window = SDL_CreateWindow(b"Synth", 0, 0, 640, 480, SDL_WINDOW_SHOWN)

wsurf = SDL_GetWindowSurface(window)
ww = wsurf.contents.w
wh = wsurf.contents.h
wrect = SDL_Rect(0, 0, ww, wh)


def hcenter(surf, y):
    w = surf.contents.w
    h = surf.contents.h
    x = (ww // 2) - (w // 2)
    return SDL_Rect(x ,y, w, h)


synth = Synth()

desired = SDL_AudioSpec(SAMPLE_RATE, AUDIO_F32SYS, 1, BLOCK_SIZE)
callback_func = SDL_AudioCallback(synth.audio_callback)
desired.callback = callback_func
devid = SDL_OpenAudioDevice(None, 0, desired, None, 0)
SDL_PauseAudioDevice(devid, 0)

font = 0
small_font = 0
for path in FONT_PATHS:
    font = TTF_OpenFont(path, 80)
    if font:
        small_font = TTF_OpenFont(path, 40)
        break

fill_color = SDL_MapRGB(wsurf.contents.format, 0 if font else 255, 0, 0)
text_color = SDL_Color(255, 255, 255, 255)

event = SDL_Event()
key = -9  # steps from A4, start at C4
mod = MOD_NONE
degree = 0
last_degree = 0

chord_text = b" "
key_text = b"Key: C"

running = True

while running:
    while SDL_PollEvent(ctypes.byref(event)) != 0:

        if event.type == SDL_QUIT:
            running = False

        elif event.type == SDL_KEYDOWN:
            op = KEY_MAP.get(event.key.keysym.scancode)
            if op is None:
                continue

            if op[0] == OP_QUIT:
                running = False
            elif op[0] == OP_SHIFT:
                key += op[1]
                if degree > 0:
                    synth.change_chord(key, degree, mod)
                key_name = ROOT_NAMES[key % 12]
                key_text = f"Key: {key_name}".encode()
            elif op[0] == OP_MOD:
                mod = op[1]
                if degree > 0:
                    synth.change_chord(key, degree, mod)
            elif op[0] == OP_PLAY:
                degree = op[1]
                synth.change_chord(key, degree, mod)
                last_degree = degree

            chord_text = synth.chord_name.encode()

        elif event.type == SDL_KEYUP:
            op = KEY_MAP.get(event.key.keysym.scancode)
            if op is None:
                continue

            if op[0] == OP_MOD:
                mod = MOD_NONE
                if degree > 0:
                    synth.change_chord(key, degree, mod)
                    chord_text = synth.chord_name.encode()
            elif op[0] == OP_PLAY:
                degree = 0
                if op[1] == last_degree:
                    synth.release()


    SDL_FillRect(wsurf, wrect, fill_color)

    if font:
        tsurf = TTF_RenderText_Blended(font, chord_text, text_color)
        trect = hcenter(tsurf, 150)
        SDL_BlitSurface(tsurf, None, wsurf, trect)
        SDL_FreeSurface(tsurf)

        tsurf = TTF_RenderText_Blended(small_font, key_text, text_color)
        trect = hcenter(tsurf, 300)
        SDL_BlitSurface(tsurf, None, wsurf, trect)
        SDL_FreeSurface(tsurf)

    SDL_UpdateWindowSurface(window)

    SDL_Delay(10)

SDL_CloseAudioDevice(devid)
TTF_CloseFont(font)
TTF_CloseFont(small_font)
TTF_Quit()
SDL_DestroyWindow(window)
SDL_Quit()
