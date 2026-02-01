# !/bin/zsh
_cef_mem_size=10000000
sudo sysctl -w net.core.rmem_default=$_cef_mem_size
sudo sysctl -w net.core.wmem_default=$_cef_mem_size
sudo sysctl -w net.core.rmem_max=$_cef_mem_size
sudo sysctl -w net.core.wmem_max=$_cef_mem_size

