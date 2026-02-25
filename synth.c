#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <SDL2/SDL.h>
#include <portaudio.h>

#define SAMPLE_RATE 16000  // Match mSBC bandwidth
#define FRAMES_PER_BUFFER 64
#define MASTER_VOL 0.25f
#define ATTACK_TIME 0.02f
#define RELEASE_TIME 0.05f
#define MAX_VOICES 16

typedef enum { VOICE_OFF, VOICE_ON, VOICE_RELEASE } VoiceState;

typedef struct {
    int midi_note;
    double freqs[3];
    double phases[3];
    VoiceState state;
    int env_pos;
    float env_level;
    int release_pos;
} Voice;

typedef struct {
    Voice voices[MAX_VOICES];
    float filter_state;
} SynthData;

// Constants for envelopes
const int ATTACK_SAMPLES = (int)(ATTACK_TIME * SAMPLE_RATE);
const int RELEASE_SAMPLES = (int)(RELEASE_TIME * SAMPLE_RATE);
const float WEIGHTS[3] = {0.6f, 0.25f, 0.15f};

double midi_to_freq(int m) {
    return 440.0 * pow(2.0, (m - 69.0) / 12.0);
}

// Audio Callback
static int patestCallback(const void *inputBuffer, void *outputBuffer,
                          unsigned long framesPerBuffer,
                          const PaStreamCallbackTimeInfo* timeInfo,
                          PaStreamCallbackFlags statusFlags,
                          void *userData) {
    SynthData *data = (SynthData*)userData;
    float *out = (float*)outputBuffer;

    float alpha = 0.2f;  // low-pass filter coefficient

    for (unsigned int i = 0; i < framesPerBuffer; i++) {
        float sample_sum = 0.0f;

        for (int v = 0; v < MAX_VOICES; v++) {
            Voice *voice = &data->voices[v];
            if (voice->state == VOICE_OFF) continue;

            // Handle Envelope
            float current_env = voice->env_level;
            if (voice->state == VOICE_ON) {
                if (voice->env_pos < ATTACK_SAMPLES) {
                    current_env += (1.0f / ATTACK_SAMPLES);
                    if (current_env > 1.0f) current_env = 1.0f;
                    voice->env_pos++;
                } else {
                    current_env = 1.0f;
                }
            } else if (voice->state == VOICE_RELEASE) {
                current_env -= (1.0f / RELEASE_SAMPLES);
                if (current_env <= 0.0f) {
                    current_env = 0.0f;
                    voice->state = VOICE_OFF;
                }
            }
            voice->env_level = current_env;

            // Synthesize 3 partials
            for (int p = 0; p < 3; p++) {
                // sine
                // sample_sum += (float)(sin(voice->phases[p]) * WEIGHTS[p] * current_env);
                // square
                // sample_sum += (voice->phases[p] < M_PI) ? WEIGHTS[p] : -WEIGHTS[p];
                // saw
                float saw = (float)(voice->phases[p] / M_PI) - 1.0f;
                sample_sum += saw * WEIGHTS[p] * current_env;

                double delta = (2.0 * M_PI * voice->freqs[p]) / SAMPLE_RATE;
                voice->phases[p] = fmod(voice->phases[p] + delta, 2.0 * M_PI);
            }
        }

        // *out++ = sample_sum * MASTER_VOL; // Left/Mono channel
        float raw_output = sample_sum * MASTER_VOL;
        // low-pass filter
        data->filter_state = data->filter_state + alpha * (raw_output - data->filter_state);
        *out++ = data->filter_state;
    }
    return paContinue;
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
    PaStream *stream;

    Pa_Initialize();
    Pa_OpenDefaultStream(&stream, 0, 1, paFloat32, SAMPLE_RATE, FRAMES_PER_BUFFER, patestCallback, &data);
    Pa_StartStream(stream);

    SDL_Init(SDL_INIT_VIDEO);
    SDL_Window *window = SDL_CreateWindow("Chord Synth", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, 400, 200, 0);

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
                int intervals[3] = {0, 4, 7}; // Default Major
                
                switch (event.key.keysym.sym) {
                    case SDLK_a: midi = 60; intervals[1] = 4; break; // C Maj
                    case SDLK_s: midi = 62; intervals[1] = 3; break; // D Min
                    case SDLK_d: midi = 64; intervals[1] = 3; break; // E Min
                    case SDLK_f: midi = 65; intervals[1] = 4; break; // F Maj
                    case SDLK_g: midi = 67; intervals[1] = 4; break; // G Maj
                    case SDLK_h: midi = 69; intervals[1] = 3; break; // A Min
                    case SDLK_j: midi = 71; intervals[1] = 3; intervals[2] = 6; break; // B Dim
                    case SDLK_k: midi = 72; intervals[1] = 4; break; // C Maj
                    case SDLK_ESCAPE: running = 0; break;
                }

                if (midi != -1) {
                    if (event.type == SDL_KEYDOWN && event.key.repeat == 0) note_on(&data, midi, intervals);
                    else if (event.type == SDL_KEYUP) note_off(&data, midi);
                }
            }
        }
        SDL_Delay(10);
    }

    Pa_StopStream(stream);
    Pa_CloseStream(stream);
    Pa_Terminate();
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}