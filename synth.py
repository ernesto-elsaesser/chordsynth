#!/usr/bin/env python3
import math
import threading
import numpy as np
import ctypes
from sdl2 import *

# Audio parameters
SR = 16000
BLOCKSIZE = 512
MASTER_VOL = 0.2

# Envelope & Filter
ATTACK = 0.02
RELEASE = 0.05
CUTOFF_HZ = 1200.0  # Low-pass filter cutoff

# Map SDL2 scancodes to MIDI
KEY_TO_MIDI = {
    SDL_SCANCODE_A: 60, SDL_SCANCODE_S: 62, SDL_SCANCODE_D: 64, SDL_SCANCODE_F: 65,
    SDL_SCANCODE_G: 67, SDL_SCANCODE_H: 69, SDL_SCANCODE_J: 71, SDL_SCANCODE_K: 72,
}

KEY_TO_INTERVALS = {
    SDL_SCANCODE_A: (0, 4, 7), SDL_SCANCODE_S: (0, 3, 7), SDL_SCANCODE_D: (0, 3, 7),
    SDL_SCANCODE_F: (0, 4, 7), SDL_SCANCODE_G: (0, 4, 7), SDL_SCANCODE_H: (0, 3, 7),
    SDL_SCANCODE_J: (0, 3, 6), SDL_SCANCODE_K: (0, 4, 7),
}

def midi_to_freq(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)

class Synth:
    def __init__(self, samplerate=SR):
        self.sr = samplerate
        self.lock = threading.Lock()
        self.voices = {}
        self.attack_samples = int(ATTACK * self.sr)
        self.release_samples = int(RELEASE * self.sr)

        # Filter coefficient alpha
        # alpha = dt / (RC + dt)
        self.alpha = (2.0 * math.pi * CUTOFF_HZ / self.sr) / (2.0 * math.pi * CUTOFF_HZ / self.sr + 1.0)

    def note_on(self, midi, intervals=(0, 4, 7)):
        with self.lock:
            if midi in self.voices: return
            freqs = [midi_to_freq(midi + i) for i in intervals]
            self.voices[midi] = {
                'freqs': freqs,
                'phases': [0.0, 0.0, 0.0],
                'state': 'on',
                'env_pos': 0,
                'env_level': 0.0,
                'release_pos': 0,
                'lpf_state': 0.0  # Memory for the one-pole filter
            }

    def note_off(self, midi):
        with self.lock:
            v = self.voices.get(midi)
            if v and v['state'] == 'on':
                v['state'] = 'release'
                v['release_pos'] = 0

    def audio_callback(self, userdata, stream, length):
        frames = length // 4
        buf = np.zeros(frames, dtype=np.float32)
        remove_list = []

        with self.lock:
            for midi, v in list(self.voices.items()):
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
                        remove_list.append(midi)

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

            for midi in remove_list: del self.voices[midi]

        result = (buf * MASTER_VOL).astype(np.float32)
        ctypes.memmove(stream, result.ctypes.data, length)

def run():
    if SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO) != 0: return

    synth = Synth()
    desired = SDL_AudioSpec(SR, AUDIO_F32SYS, 1, BLOCKSIZE)
    callback_func = SDL_AudioCallback(synth.audio_callback)
    desired.callback = callback_func
    devid = SDL_OpenAudioDevice(None, 0, desired, None, 0)
    SDL_PauseAudioDevice(devid, 0)

    window = SDL_CreateWindow(b"Sawtooth LPF Synth", SDL_WINDOWPOS_CENTERED,
                              SDL_WINDOWPOS_CENTERED, 400, 300, SDL_WINDOW_SHOWN)
    running, event, pressed_keys = True, SDL_Event(), set()

    try:
        while running:
            while SDL_PollEvent(ctypes.byref(event)) != 0:
                if event.type == SDL_QUIT: running = False
                elif event.type == SDL_KEYDOWN:
                    sc = event.key.keysym.scancode
                    if sc == SDL_SCANCODE_ESCAPE: running = False
                    elif sc in KEY_TO_MIDI and sc not in pressed_keys:
                        pressed_keys.add(sc)
                        synth.note_on(KEY_TO_MIDI[sc], intervals=KEY_TO_INTERVALS[sc])
                elif event.type == SDL_KEYUP:
                    sc = event.key.keysym.scancode
                    if sc in KEY_TO_MIDI:
                        pressed_keys.discard(sc)
                        synth.note_off(KEY_TO_MIDI[sc])
            SDL_Delay(10)
    finally:
        SDL_CloseAudioDevice(devid); SDL_DestroyWindow(window); SDL_Quit()

if __name__ == '__main__':
    run()

