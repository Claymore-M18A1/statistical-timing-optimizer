Instruction if you're using docker:

1. Run docker

2. Install OpenROAD

3. Install OpenSTA & Required kits

apt update
apt install -y git cmake g++ libreadline-dev flex bison
apt install -y tcl-dev tcl

cd /tmp
git clone https://github.com/The-OpenROAD-Project/OpenSTA.git
cd OpenSTA

git submodule update --init --recursive  
mkdir build && cd build

cmake .. -DENABLE_SPEF_READER=ON
make -j$(nproc)

4. Run Simulated Annealing
cd /project
python3 simulated_annealing.py
