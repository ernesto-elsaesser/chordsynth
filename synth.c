#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <SDL2/SDL.h>

#define SAMPLE_RATE 16000  // Match mSBC bandwidth
#define FRAMES_PER_BUFFER 128
#define MASTER_VOL 0.25f
#define ATTACK_TIME 0.02f
#define RELEASE_TIME 0.05f
#define MAX_VOICES 8

typedef enum { VOICE_OFF, VOICE_ON, VOICE_RELEASE } VoiceState;

typedef struct {
    int midi_note;
    double freqs[3];
    double phases[3];
    VoiceState state;
    int env_pos;
    float env_level;
} Voice;

typedef struct {
    Voice voices[MAX_VOICES];
    float filter_state;
} SynthData;

const int ATTACK_SAMPLES = (int)(ATTACK_TIME * SAMPLE_RATE);
const int RELEASE_SAMPLES = (int)(RELEASE_TIME * SAMPLE_RATE);
const float WEIGHTS[3] = {0.6f, 0.25f, 0.15f};

double midi_to_freq(int m) {
    return 440.0 * pow(2.0, (m - 69.0) / 12.0);
}

void sdlAudioCallback(void* userData, Uint8* stream, int len) {
    SynthData* data = (SynthData*)userData;
    float* out = (float*)stream;
    int frames = len / sizeof(float);
    float alpha = 0.2f; // Low-pass filter coefficient

    for (int i = 0; i < frames; i++) {
        float sample_sum = 0.0f;

        for (int v = 0; v < MAX_VOICES; v++) {
            Voice *voice = &data->voices[v];
            if (voice->state == VOICE_OFF) continue;

            // Envelope Logic
            if (voice->state == VOICE_ON) {
                if (voice->env_pos < ATTACK_SAMPLES) {
                    voice->env_level += (1.0f / ATTACK_SAMPLES);
                    if (voice->env_level > 1.0f) voice->env_level = 1.0f;
                    voice->env_pos++;
                }
            } else if (voice->state == VOICE_RELEASE) {
                voice->env_level -= (1.0f / RELEASE_SAMPLES);
                if (voice->env_level <= 0.0f) {
                    voice->env_level = 0.0f;
                    voice->state = VOICE_OFF;
                }
            }

            // Sawtooth Synthesis
            for (int p = 0; p < 3; p++) {
                // sine
                // sample_sum += (float)(sin(voice->phases[p]) * WEIGHTS[p] * current_env);
                // square
                // sample_sum += (voice->phases[p] < M_PI) ? WEIGHTS[p] : -WEIGHTS[p];
                // saw
                float saw = (float)(voice->phases[p] / M_PI) - 1.0f;
                sample_sum += saw * WEIGHTS[p] * voice->env_level;

                double delta = (2.0 * M_PI * voice->freqs[p]) / SAMPLE_RATE;
                voice->phases[p] = fmod(voice->phases[p] + delta, 2.0 * M_PI);
            }
        }

        // Apply Master Volume and Low-Pass Filter
        float raw_output = sample_sum * MASTER_VOL;
        data->filter_state = data->filter_state + alpha * (raw_output - data->filter_state);
        out[i] = data->filter_state;
    }
}

void note_on(SynthData *data, int midi, int intervals[3]) {
    for (int i = 0; i < MAX_VOICES; i++) {
        if (data->voices[i].midi_note == midi && data->voices[i].state != VOICE_OFF) return;
    }
    for (int i = 0; i < MAX_VOICES; i++) {
        if (data->voices[i].state == VOICE_OFF) {
            data->voices[i].midi_note = midi;
            for (int j = 0; j < 3; j++) {
                data->voices[i].freqs[j] = midi_to_freq(midi + intervals[j]);
                data->voices[i].phases[j] = 0.0;
            }
            data->voices[i].state = VOICE_ON;
            data->voices[i].env_pos = 0;
            data->voices[i].env_level = 0.0f;
            break;
        }
    }
}

void note_off(SynthData *data, int midi) {
    for (int i = 0; i < MAX_VOICES; i++) {
        if (data->voices[i].midi_note == midi && data->voices[i].state == VOICE_ON) {
            data->voices[i].state = VOICE_RELEASE;
        }
    }
}

int main(int argc, char* argv[]) {
    SynthData data = {0};

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO) < 0) return -1;

    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = SAMPLE_RATE;
    want.format = AUDIO_F32;
    want.channels = 1;
    want.samples = FRAMES_PER_BUFFER;
    want.callback = sdlAudioCallback;
    want.userdata = &data;

    SDL_AudioDeviceID dev = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (dev == 0) {
        printf("Failed to open audio device!");
        return -1;
    }

    SDL_PauseAudioDevice(dev, 0);

    SDL_Window* window = SDL_CreateWindow("SDL2 Only Synth", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, 200, 200, 0);

    SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    SDL_RenderPresent(renderer);

    int running = 1;
    SDL_Event event;
    while (running) {
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) running = 0;
            if (event.type == SDL_KEYDOWN || event.type == SDL_KEYUP) {
                int midi = -1;
                int intervals[3] = {0, 4, 7};

                switch (event.key.keysym.sym) {
                    case SDLK_a: midi = 60; intervals[1] = 4; break;
                    case SDLK_s: midi = 62; intervals[1] = 3; break;
                    case SDLK_d: midi = 64; intervals[1] = 3; break;
                    case SDLK_f: midi = 65; intervals[1] = 4; break;
                    case SDLK_g: midi = 67; intervals[1] = 4; break;
                    case SDLK_h: midi = 69; intervals[1] = 3; break;
                    case SDLK_j: midi = 71; intervals[1] = 3; intervals[2] = 6; break;
                    case SDLK_k: midi = 72; intervals[1] = 4; break;
                }

                if (midi != -1) {
                    // Lock the audio device while modifying shared data
                    SDL_LockAudioDevice(dev);
                    if (event.type == SDL_KEYDOWN && event.key.repeat == 0) note_on(&data, midi, intervals);
                    else if (event.type == SDL_KEYUP) note_off(&data, midi);
                    SDL_UnlockAudioDevice(dev);
                }
            }
        }
    }

    SDL_CloseAudioDevice(dev);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
