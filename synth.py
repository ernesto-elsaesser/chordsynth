#!/usr/bin/env python3
"""Simple 3-note chord synthesizer.

Uses `sounddevice` for audio callback synthesis and `pygame` for keyboard
event handling. Press mapped keys to play a sustained 3-note (major) chord
while the key is held.

Keys mapped: a s d f g h j k -> notes around middle C
"""
import math
import threading
import numpy as np
import sounddevice as sd
import pygame

# Audio parameters
SR = 44100
BLOCKSIZE = 512
MASTER_VOL = 0.25

# Envelope times (seconds)
ATTACK = 0.02
RELEASE = 0.05

# Map keyboard keys (pygame key names) to MIDI note numbers (C4 = 60)
KEY_TO_MIDI = {
    'a': 60,  # C4
    's': 62,  # D4
    'd': 64,  # E4
    'f': 65,  # F4
    'g': 67,  # G4
    'h': 69,  # A4
    'j': 71,  # B4
    'k': 72,  # C5
}

# Chord intervals per key according to the C major scale
# C: major, D: minor, E: minor, F: major, G: major, A: minor, B: diminished, C: major
KEY_TO_INTERVALS = {
    'a': (0, 4, 7),  # C major
    's': (0, 3, 7),  # D minor
    'd': (0, 3, 7),  # E minor
    'f': (0, 4, 7),  # F major
    'g': (0, 4, 7),  # G major
    'h': (0, 3, 7),  # A minor
    'j': (0, 3, 6),  # B diminished
    'k': (0, 4, 7),  # C major (octave)
}


def midi_to_freq(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


class Synth:
    def __init__(self, samplerate=SR):
        self.sr = samplerate
        self.lock = threading.Lock()
        # active voices keyed by midi base note
        self.voices = {}
        self.attack_samples = int(ATTACK * self.sr)
        self.release_samples = int(RELEASE * self.sr)

    def note_on(self, midi, intervals=(0, 4, 7)):
        with self.lock:
            if midi in self.voices:
                # already playing
                return
            # build chord according to provided intervals
            freqs = [midi_to_freq(midi + i) for i in intervals]
            phases = [0.0, 0.0, 0.0]
            voice = {
                'freqs': freqs,
                'phases': phases,
                'state': 'on',
                'env_pos': 0,
                'env_level': 0.0,
                'release_pos': 0,
            }
            self.voices[midi] = voice

    def note_off(self, midi):
        with self.lock:
            v = self.voices.get(midi)
            if v and v['state'] == 'on':
                v['state'] = 'release'
                v['release_pos'] = 0

    def audio_callback(self, outdata, frames, time, status):
        if status:
            print('Audio status:', status)
        t_idx = np.arange(frames)
        buf = np.zeros(frames, dtype=np.float32)

        remove_list = []

        with self.lock:
            for midi, v in list(self.voices.items()):
                freqs = v['freqs']
                phases = v['phases']

                # build envelope for this block
                if v['state'] == 'on':
                    if v['env_pos'] < self.attack_samples and self.attack_samples > 0:
                        n_attack = min(self.attack_samples - v['env_pos'], frames)
                        env = np.ones(frames, dtype=np.float32) * 1.0
                        ramp = np.linspace(v['env_level'], 1.0, n_attack, dtype=np.float32)
                        env[:n_attack] = ramp
                        if n_attack < frames:
                            env[n_attack:] = 1.0
                        v['env_pos'] += frames
                        v['env_level'] = float(env[-1])
                    else:
                        env = np.ones(frames, dtype=np.float32) * float(v['env_level'])
                else:  # release
                    remaining = max(self.release_samples - v['release_pos'], 0)
                    n_release = min(frames, remaining)
                    env = np.zeros(frames, dtype=np.float32)
                    if n_release > 0:
                        env[:n_release] = np.linspace(v['env_level'], 0.0, n_release, dtype=np.float32)
                    # rest are zeros
                    v['release_pos'] += frames
                    v['env_level'] = float(env[min(n_release - 1, frames - 1)] if n_release > 0 else 0.0)
                    if v['release_pos'] >= self.release_samples:
                        remove_list.append(midi)

                # sum partials (simple additive sine)
                # give a small relative amplitude roll-off for upper partials
                weights = [0.6, 0.25, 0.15]
                for i, f in enumerate(freqs):
                    delta = 2.0 * math.pi * f / self.sr
                    ph = phases[i]
                    samples = np.sin(ph + delta * t_idx).astype(np.float32)
                    phases[i] = (ph + delta * frames) % (2.0 * math.pi)
                    buf += weights[i] * samples * env

                v['phases'] = phases

            for midi in remove_list:
                del self.voices[midi]

        # apply master volume and ensure shape (frames, channels)
        out = (buf * MASTER_VOL).reshape(-1, 1)
        outdata[:] = out


def run():
    synth = Synth()

    # start audio stream
    stream = sd.OutputStream(channels=1, callback=synth.audio_callback,
                             samplerate=SR, blocksize=BLOCKSIZE)
    stream.start()

    # init pygame for keyboard
    pygame.init()
    screen = pygame.display.set_mode((480, 120))
    pygame.display.set_caption('Chord Synth')




    running = True
    pressed_keys = set()

    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    name = pygame.key.name(event.key)
                    if name == 'escape':
                        running = False
                        break
                    if name in KEY_TO_MIDI and name not in pressed_keys:
                        pressed_keys.add(name)
                        intervals = KEY_TO_INTERVALS.get(name, (0, 4, 7))
                        synth.note_on(KEY_TO_MIDI[name], intervals=intervals)
                elif event.type == pygame.KEYUP:
                    name = pygame.key.name(event.key)
                    if name in KEY_TO_MIDI and name in pressed_keys:
                        pressed_keys.remove(name)
                        synth.note_off(KEY_TO_MIDI[name])



            pygame.display.flip()
            pygame.time.wait(10)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        stream.close()
        pygame.quit()


if __name__ == '__main__':
    run()
