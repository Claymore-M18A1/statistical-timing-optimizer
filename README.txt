
docker run --rm -it \
  -v $(pwd)/flow:/OpenROAD-flow-scripts/flow \
  -v $(pwd)/md_sa_project:/project \
  openroad/flow-ubuntu22.04-builder:afc3ce \
  /bin/bash

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



rm -f /usr/local/bin/opensta
ln -s /tmp/OpenSTA/app/sta /usr/local/bin/opensta

pip install matplotlib

cd /project
python3 simulated_annealing.py