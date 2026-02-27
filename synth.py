#!/usr/bin/env python3
import math
import numpy as np
import ctypes
from pysdl import *  # local PySDL2 folder

# Audio parameters
SR = 16000
BLOCKSIZE = 512
MASTER_VOL = 0.2

# Envelope & Filter
ATTACK = 0.02
RELEASE = 0.05
CUTOFF_HZ = 1200.0  # Low-pass filter cutoff

PITCH_TO_MIDI = {
    "C": 60,
    "D": 62,
    "E": 64,
    "F": 65,
    "G": 67,
    "A": 69,
    "B": 71,
}

SCANCODE_TO_PITCH = {
    SDL_SCANCODE_1: "C",
    SDL_SCANCODE_2: "D",
    SDL_SCANCODE_3: "E",
    SDL_SCANCODE_4: "F",
    SDL_SCANCODE_5: "G",
    SDL_SCANCODE_6: "A",
    SDL_SCANCODE_7: "B",
    SDL_SCANCODE_RSHIFT: "C",
    SDL_SCANCODE_SPACE: "C",
    SDL_SCANCODE_RETURN: "D",
    SDL_SCANCODE_B: "E",
    SDL_SCANCODE_Y: "F",
    SDL_SCANCODE_X: "G",
    SDL_SCANCODE_A: "A",
    SDL_SCANCODE_H: "B",
}


def midi_to_freq(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


class Synth:
    def __init__(self, samplerate=SR):
        self.sr = samplerate
        self.voices = {}
        self.attack_samples = int(ATTACK * self.sr)
        self.release_samples = int(RELEASE * self.sr)

        # Filter coefficient alpha
        self.alpha = (2.0 * math.pi * CUTOFF_HZ / self.sr) / (2.0 * math.pi * CUTOFF_HZ / self.sr + 1.0)

    def note_on(self, pitch, intervals, shift):
        if pitch in self.voices:
            return
        midi = PITCH_TO_MIDI[pitch] + shift
        freqs = [midi_to_freq(midi + i) for i in intervals]
        self.voices[pitch] = {
            'freqs': freqs,
            'phases': [0.0, 0.0, 0.0],
            'state': 'on',
            'env_pos': 0,
            'env_level': 0.0,
            'release_pos': 0,
            'lpf_state': 0.0  # Memory for the one-pole filter
        }

    def note_off(self, pitch):
        v = self.voices.get(pitch)
        if v and v['state'] == 'on':
            v['state'] = 'release'
            v['release_pos'] = 0

    def audio_callback(self, userdata, stream, length):
        frames = length // 4
        buf = np.zeros(frames, dtype=np.float32)
        remove_list = []

        for pitch, v in list(self.voices.items()):
            # --- Envelope Logic ---
            if v['state'] == 'on':
                if v['env_pos'] < self.attack_samples:
                    n_attack = min(self.attack_samples - v['env_pos'], frames)
                    env = np.ones(frames, dtype=np.float32)
                    env[:n_attack] = np.linspace(v['env_level'], 1.0, n_attack)
                    v['env_pos'] += frames
                    v['env_level'] = float(env[-1])
                else:
                    env = np.ones(frames, dtype=np.float32) * float(v['env_level'])
            else:
                n_release = min(frames, max(self.release_samples - v['release_pos'], 0))
                env = np.zeros(frames, dtype=np.float32)
                if n_release > 0:
                    env[:n_release] = np.linspace(v['env_level'], 0.0, n_release)
                v['release_pos'] += frames
                v['env_level'] = float(env[n_release-1] if n_release > 0 else 0.0)
                if v['release_pos'] >= self.release_samples:
                    remove_list.append(pitch)

            # --- Sawtooth Synthesis ---
            voice_buf = np.zeros(frames, dtype=np.float32)
            weights = [0.5, 0.3, 0.2]
            for i, f in enumerate(v['freqs']):
                delta = 2.0 * math.pi * f / self.sr
                # Generate phase array
                phases = (v['phases'][i] + delta * np.arange(frames)) % (2.0 * math.pi)
                # Sawtooth formula: 2 * (phase / 2pi) - 1
                samples = (2.0 * (phases / (2.0 * math.pi)) - 1.0).astype(np.float32)
                v['phases'][i] = (v['phases'][i] + delta * frames) % (2.0 * math.pi)
                voice_buf += weights[i] * samples * env

            # --- One-Pole Low-Pass Filter ---
            # y[n] = y[n-1] + alpha * (x[n] - y[n-1])
            filtered_voice = np.zeros(frames, dtype=np.float32)
            last_y = v['lpf_state']
            for n in range(frames):
                last_y = last_y + self.alpha * (voice_buf[n] - last_y)
                filtered_voice[n] = last_y
            v['lpf_state'] = last_y

            buf += filtered_voice

        for pitch in remove_list:
            del self.voices[pitch]

        result = (buf * MASTER_VOL).astype(np.float32)
        ctypes.memmove(stream, result.ctypes.data, length)


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
jstick = None
intervals = 0, 4, 7
shift = 0
running = True

while running:
    while SDL_PollEvent(ctypes.byref(event)) != 0:
        if event.type == SDL_QUIT:
            running = False
        elif event.type == SDL_KEYDOWN:
            sc = event.key.keysym.scancode
            if sc in (SDL_SCANCODE_POWER, SDL_SCANCODE_ESCAPE):
                running = False
            elif sc == SDL_SCANCODE_UP:
                shift = 12
            elif sc == SDL_SCANCODE_DOWN:
                shift = -12
            elif sc == SDL_SCANCODE_LEFT:
                intervals = 0, 3, 7
            elif sc == SDL_SCANCODE_RIGHT:
                intervals = 0, 7
            else:
                pitch = SCANCODE_TO_PITCH.get(sc)
                if pitch is not None:
                    synth.note_on(pitch, intervals, shift)
        elif event.type == SDL_KEYUP:
            sc = event.key.keysym.scancode
            if sc in {SDL_SCANCODE_UP, SDL_SCANCODE_DOWN}:
                shift = 0
            if sc in {SDL_SCANCODE_LEFT, SDL_SCANCODE_RIGHT}:
                intervals = 0, 4, 7
            else:
                pitch = SCANCODE_TO_PITCH.get(sc)
                if pitch is not None:
                    synth.note_off(pitch)
        elif event.type == SDL_JOYDEVICEADDED:
            jstick = SDL_JoystickOpen(event.jdevice.which)
        elif event.type == SDL_JOYHATMOTION:
            sc = event.jhat.value
            if sc == SDL_HAT_UP:
                intervals = 0, 4, 7
            elif sc == SDL_HAT_LEFT:
                intervals = 0, 7
            elif sc == SDL_HAT_DOWN:
                intervals = 0, 3, 7

    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
    SDL_RenderClear(renderer)
    SDL_SetRenderDrawColor(renderer, 255, 0, 0, 255)
    for offset in intervals:
        rct = SDL_Rect(20 + offset * 40, 20, 20, 20)
        SDL_RenderFillRect(renderer, rct)
    for offset, pitch in enumerate(PITCH_TO_MIDI):
        on = pitch in synth.voices
        SDL_SetRenderDrawColor(renderer, 0, 255 if on else 0, 0 if on else 255, 255)
        rct = SDL_Rect(20 + offset * 40, 50, 20, 20)
        SDL_RenderFillRect(renderer, rct)
    SDL_RenderPresent(renderer)
    
    SDL_Delay(10)

SDL_CloseAudioDevice(devid)
SDL_DestroyRenderer(renderer)
SDL_DestroyWindow(window)
SDL_Quit()
