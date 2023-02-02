import torch.nn as nn

from omegaconf import DictConfig
from funcx import FuncXClient

from appfl.misc import Dataset
from appfl.funcx.funcx_test_server import APPFLFuncXTestServer


def run_server(
    cfg: DictConfig,
    model: nn.Module,
    loss_fn: nn.Module,
    fxc: FuncXClient,
    test_data: Dataset = Dataset(),
    val_data: Dataset = Dataset(),
):
    serv = APPFLFuncXTestServer(cfg, fxc)

    serv.set_server_dataset(validation_dataset=val_data, testing_dataset=test_data)

    serv.run(model, loss_fn)
