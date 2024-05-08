# create or recreate conda environment called blinder with python version 3.10
conda deactivate
conda env remove -n blinder
conda create -n -y blinder python=3.10
conda activate blinder

pip install -r src/api/requirements.txt

# install pre-commit hooks
pre-commit install
