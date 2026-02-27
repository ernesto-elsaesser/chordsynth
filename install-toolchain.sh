wget https://toolchains.bootlin.com/downloads/releases/toolchains/aarch64/tarballs/aarch64--glibc--stable-2024.05-1.tar.xz
tar -xf aarch64--glibc--stable-2024.05-1.tar.xz
cd aarch64--glibc--stable-2024.05-1/aarch64-buildroot-linux-gnu
cp -r /usr/include/SDL2 include
cp -r ./target_lib/* lib
cd lib
ln -s libSDL2-2.0.so.0 libSDL2.so
cd ../include/SDL2
rm SDL_config.h
ln -s SDL_config_unix.h SDL_config.h
