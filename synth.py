#!/usr/bin/env python3
import math
import ctypes

# local PySDL2 folder
from pysdl import *
from pysdl.sdlttf import *

# TODO: chord variation live

SR = 16000
BLOCKSIZE = 512
MASTER_VOL = 0.2

ATTACK = 0.02
RELEASE = 0.05
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


class Voice:

    def __init__(self, root, above):

        chord_code = "+".join(str(i) for i in above)
        self.name = ROOT_NAMES[root % 12] + CHORD_NAMES[chord_code]
        offsets = [0] + above
        self.freqs = [440.0 * 2 ** ((root + o) / 12.0) for o in offsets]
        self.weights = [1.0] * len(offsets)
        self.phases = [0.0] * len(offsets)
        self.pressed = True
        self.env_pos = 0
        self.env_level = 0.0
        self.release_pos = 0
        self.lpf_state = 0.0  # Memory for the one-pole filter


class Synth:
    def __init__(self, samplerate: int = SR):
        self.sr = samplerate
        self.voices = {}
        self.attack_samples = int(ATTACK * self.sr)
        self.release_samples = int(RELEASE * self.sr)

        self.key = -9  # steps from A4, start at C4
        self.mod = MOD_NONE

        # Filter coefficient alpha
        self.alpha = (2.0 * math.pi * CUTOFF_HZ / self.sr) / (2.0 * math.pi * CUTOFF_HZ / self.sr + 1.0)

    def shift_key(self, delta: int) -> str:
        self.key += delta
        return ROOT_NAMES[self.key % 12]

    def note_on(self, degree: int) -> Voice:
        if degree in self.voices:
            return self.voices[degree]
        root = self.key + SCALE[degree]
        chord = CHORDS[self.mod][degree]
        voice = Voice(root, chord)
        self.voices[degree] = voice
        return voice

    def note_off(self, degree: int):
        v = self.voices.get(degree)
        if v and v.pressed:
            v.pressed = False

    def audio_callback(self, userdata, stream, length):
        frames = length // 4
        
        # Create output buffer as ctypes float array
        out_buf = (ctypes.c_float * frames)()
        remove_list = []

        for degree, v in self.voices.items():
            # --- Envelope Logic ---
            if v.pressed:
                if v.env_pos < self.attack_samples:
                    n_attack = min(self.attack_samples - v.env_pos, frames)
                    # Linear interpolation for attack
                    attack_start = v.env_level
                    attack_end = 1.0
                    attack_duration = self.attack_samples - (v.env_pos - n_attack)
                    
                    env = []
                    for i in range(frames):
                        if i < n_attack:
                            ratio = i / attack_duration if attack_duration > 0 else 1.0
                            env.append(attack_start + (attack_end - attack_start) * ratio)
                        else:
                            env.append(1.0)
                    
                    v.env_pos += frames
                    v.env_level = env[-1]
                else:
                    env = [1.0] * frames
            else:
                n_release = min(frames, max(self.release_samples - v.release_pos, 0))
                env = []
                release_start = v.env_level
                release_duration = self.release_samples - (v.release_pos - n_release) if n_release > 0 else 1.0
                
                for i in range(frames):
                    if i < n_release and release_duration > 0:
                        ratio = i / release_duration
                        env.append(release_start * (1.0 - ratio))
                    else:
                        env.append(0.0)
                
                v.release_pos += frames
                v.env_level = env[n_release - 1] if n_release > 0 else 0.0
                if v.release_pos >= self.release_samples:
                    remove_list.append(degree)

            # --- Sawtooth Synthesis ---
            voice_buf = [0.0] * frames
            
            for osc_idx, f in enumerate(v.freqs):
                delta = 2.0 * math.pi * f / self.sr
                phase = v.phases[osc_idx]
                
                for n in range(frames):
                    # Sawtooth formula: 2 * (phase / 2pi) - 1
                    sample = 2.0 * (phase / (2.0 * math.pi)) - 1.0
                    voice_buf[n] += v.weights[osc_idx] * sample * env[n]
                    phase = (phase + delta) % (2.0 * math.pi)
                
                v.phases[osc_idx] = phase

            # --- One-Pole Low-Pass Filter ---
            filtered_voice = [0.0] * frames
            last_y = v.lpf_state
            for n in range(frames):
                last_y = last_y + self.alpha * (voice_buf[n] - last_y)
                filtered_voice[n] = last_y
            v.lpf_state = last_y

            # Add to output buffer
            for n in range(frames):
                out_buf[n] += filtered_voice[n]

        for degree in remove_list:
            del self.voices[degree]

        # Scale and copy to SDL stream
        out_ptr = ctypes.cast(stream, ctypes.POINTER(ctypes.c_float))
        for n in range(frames):
            out_ptr[n] = out_buf[n] * MASTER_VOL


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

desired = SDL_AudioSpec(SR, AUDIO_F32SYS, 1, BLOCKSIZE)
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
current_key = b"Key: C"
last_chord = b" "
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
            if op[0] == OP_SHIFT:
                key = synth.shift_key(op[1])
                current_key = f"Key: {key}".encode()
            elif op[0] == OP_MOD:
                synth.mod = op[1]
            elif op[0] == OP_PLAY:
                voice = synth.note_on(op[1])
                last_chord = voice.name.encode()

        elif event.type == SDL_KEYUP:
            op = KEY_MAP.get(event.key.keysym.scancode)
            if op is None:
                continue
            if op[0] == OP_MOD:
                synth.mod = MOD_NONE
            elif op[0] == OP_PLAY:
                synth.note_off(op[1])

    SDL_FillRect(wsurf, wrect, fill_color)

    if font:
        tsurf = TTF_RenderText_Blended(font, last_chord, text_color)
        trect = hcenter(tsurf, 150)
        SDL_BlitSurface(tsurf, None, wsurf, trect)
        SDL_FreeSurface(tsurf)

        tsurf = TTF_RenderText_Blended(small_font, current_key, text_color)
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
