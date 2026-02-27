#!/usr/bin/env python3
import math
import ctypes
from pysdl import *  # local PySDL2 folder

# TODO:
# - show current key
# - chord variation live


SR = 16000
BLOCKSIZE = 512
MASTER_VOL = 0.3

ATTACK = 0.02
RELEASE = 0.05
CUTOFF_HZ = 1200.0  # Low-pass filter cutoff


SCANCODE_TO_DEGREE = {
    SDL_SCANCODE_1: 1,
    SDL_SCANCODE_2: 2,
    SDL_SCANCODE_3: 3,
    SDL_SCANCODE_4: 4,
    SDL_SCANCODE_5: 5,
    SDL_SCANCODE_6: 6,
    SDL_SCANCODE_7: 7,
    # SDL_SCANCODE_RSHIFT: 1,
    SDL_SCANCODE_SPACE: 1,
    SDL_SCANCODE_RETURN: 2,
    SDL_SCANCODE_B: 3,
    SDL_SCANCODE_Y: 4,
    SDL_SCANCODE_X: 5,
    SDL_SCANCODE_A: 6,
    SDL_SCANCODE_H: 7,
}

SCALE = [None, 0, 2, 4, 5, 7, 9, 11]  # major scale


def midi_to_freq(shift):
    return 440.0 * 2 ** (shift / 12.0)


class Synth:
    def __init__(self, samplerate=SR):
        self.sr = samplerate
        self.voices = {}
        self.attack_samples = int(ATTACK * self.sr)
        self.release_samples = int(RELEASE * self.sr)

        self.key = -9  # steps from A4, start at C4
        self.mod = "maj"

        # Filter coefficient alpha
        self.alpha = (2.0 * math.pi * CUTOFF_HZ / self.sr) / (2.0 * math.pi * CUTOFF_HZ / self.sr + 1.0)

    def note_on(self, degree):
        if degree in self.voices:
            return
        root = self.key + SCALE[degree]
        chord = [0]
        if self.mod == "sus4":
            chord.append(5)
        elif self.mod != "5":
            is_maj = degree in {1, 4, 5}
            if self.mod == "m":
                is_maj = not is_maj
            chord.append(4 if is_maj else 3)
        is_dim = degree == 7
        chord.append(6 if is_dim else 7)
        if self.mod == "7":
            chord.append(11)
        freqs = [440.0 * 2 ** ((root + i) / 12.0) for i in chord]
        self.voices[degree] = {
            'freqs': freqs,
            'phases': [0.0, 0.0, 0.0],
            'state': 'on',
            'env_pos': 0,
            'env_level': 0.0,
            'release_pos': 0,
            'lpf_state': 0.0  # Memory for the one-pole filter
        }

    def note_off(self, degree):
        v = self.voices.get(degree)
        if v and v['state'] == 'on':
            v['state'] = 'release'
            v['release_pos'] = 0

    def audio_callback(self, userdata, stream, length):
        frames = length // 4
        
        # Create output buffer as ctypes float array
        out_buf = (ctypes.c_float * frames)()
        remove_list = []

        for degree, v in self.voices.items():
            # --- Envelope Logic ---
            if v['state'] == 'on':
                if v['env_pos'] < self.attack_samples:
                    n_attack = min(self.attack_samples - v['env_pos'], frames)
                    # Linear interpolation for attack
                    attack_start = v['env_level']
                    attack_end = 1.0
                    attack_duration = self.attack_samples - (v['env_pos'] - n_attack)
                    
                    env = []
                    for i in range(frames):
                        if i < n_attack:
                            ratio = i / attack_duration if attack_duration > 0 else 1.0
                            env.append(attack_start + (attack_end - attack_start) * ratio)
                        else:
                            env.append(1.0)
                    
                    v['env_pos'] += frames
                    v['env_level'] = env[-1]
                else:
                    env = [1.0] * frames
            else:
                n_release = min(frames, max(self.release_samples - v['release_pos'], 0))
                env = []
                release_start = v['env_level']
                release_duration = self.release_samples - (v['release_pos'] - n_release) if n_release > 0 else 1.0
                
                for i in range(frames):
                    if i < n_release and release_duration > 0:
                        ratio = i / release_duration
                        env.append(release_start * (1.0 - ratio))
                    else:
                        env.append(0.0)
                
                v['release_pos'] += frames
                v['env_level'] = env[n_release - 1] if n_release > 0 else 0.0
                if v['release_pos'] >= self.release_samples:
                    remove_list.append(degree)

            # --- Sawtooth Synthesis ---
            voice_buf = [0.0] * frames
            weights = [0.5, 0.3, 0.2]
            
            for osc_idx, f in enumerate(v['freqs']):
                delta = 2.0 * math.pi * f / self.sr
                phase = v['phases'][osc_idx]
                
                for n in range(frames):
                    # Sawtooth formula: 2 * (phase / 2pi) - 1
                    sample = 2.0 * (phase / (2.0 * math.pi)) - 1.0
                    voice_buf[n] += weights[osc_idx] * sample * env[n]
                    phase = (phase + delta) % (2.0 * math.pi)
                
                v['phases'][osc_idx] = phase

            # --- One-Pole Low-Pass Filter ---
            filtered_voice = [0.0] * frames
            last_y = v['lpf_state']
            for n in range(frames):
                last_y = last_y + self.alpha * (voice_buf[n] - last_y)
                filtered_voice[n] = last_y
            v['lpf_state'] = last_y

            # Add to output buffer
            for n in range(frames):
                out_buf[n] += filtered_voice[n]

        for degree in remove_list:
            del self.voices[degree]

        # Scale and copy to SDL stream
        out_ptr = ctypes.cast(stream, ctypes.POINTER(ctypes.c_float))
        for n in range(frames):
            out_ptr[n] = out_buf[n] * MASTER_VOL


status = SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO)
if status != 0:
    exit()

synth = Synth()

desired = SDL_AudioSpec(SR, AUDIO_F32SYS, 1, BLOCKSIZE)
callback_func = SDL_AudioCallback(synth.audio_callback)
desired.callback = callback_func
devid = SDL_OpenAudioDevice(None, 0, desired, None, 0)
SDL_PauseAudioDevice(devid, 0)

window = SDL_CreateWindow(b"Synth", 0, 0, 640, 480, SDL_WINDOW_SHOWN)
renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC)

event = SDL_Event()
running = True

while running:
    while SDL_PollEvent(ctypes.byref(event)) != 0:
        if event.type == SDL_QUIT:
            running = False
        elif event.type == SDL_KEYDOWN:
            sc = event.key.keysym.scancode
            if sc in (SDL_SCANCODE_POWER, SDL_SCANCODE_ESCAPE):
                running = False
            elif sc == SDL_SCANCODE_PAGEUP: # L1
                synth.key += 12
            elif sc == SDL_SCANCODE_PAGEDOWN: # R1
                synth.key -= 12
            elif sc == SDL_SCANCODE_F1: # L2
                synth.key += 1
            elif sc == SDL_SCANCODE_F2: # R2
                synth.key -= 1
            elif sc == SDL_SCANCODE_UP:
                synth.mod = "m"  # switch between major and minor
            elif sc == SDL_SCANCODE_DOWN:
                synth.mod = "sus4"
            elif sc == SDL_SCANCODE_LEFT:
                synth.mod = "5"
            elif sc == SDL_SCANCODE_RIGHT:
                synth.mod = "7"
            else:
                degree = SCANCODE_TO_DEGREE.get(sc)
                if degree is not None:
                    synth.note_on(degree)
        elif event.type == SDL_KEYUP:
            sc = event.key.keysym.scancode
            if sc in {SDL_SCANCODE_UP, SDL_SCANCODE_DOWN, SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT}:
                synth.mod = ""
            else:
                degree = SCANCODE_TO_DEGREE.get(sc)
                if degree is not None:
                    synth.note_off(degree)

    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
    SDL_RenderClear(renderer)
    # TODO: print current chord via TTF module
    SDL_RenderPresent(renderer)
    
    SDL_Delay(10)

SDL_CloseAudioDevice(devid)
SDL_DestroyRenderer(renderer)
SDL_DestroyWindow(window)
SDL_Quit()
