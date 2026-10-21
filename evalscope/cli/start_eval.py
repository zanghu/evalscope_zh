# Copyright (c) Alibaba, Inc. and its affiliates.
from evalscope.cli.base import ArgumentParserWithSubParsers, CLICommand


def subparser_func(args):
    """Function which will be called for a specific sub parser."""
    return EvalCMD(args)


class EvalCMD(CLICommand):
    name = 'eval'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: ArgumentParserWithSubParsers) -> None:
        """define args for create pipeline template command."""
        from evalscope.arguments import add_argument

        parser = parsers.add_parser(EvalCMD.name)
        add_argument(parser)
        parser.add_argument(
            '--task-config',
            type=str,
            help='Complete TaskConfig JSON/YAML file. When set, this file supplies all task settings.',
        )
        parser.set_defaults(func=subparser_func)

    def execute(self) -> None:
        """Run a complete task file or the traditional CLI arguments."""
        from evalscope.run import run_task

        task_config = getattr(self.args, 'task_config', None)
        if task_config:
            if self.args.eval_config:
                raise ValueError('Use --task-config for a complete task, or --eval-config for a backend, not both.')
            run_task(task_config)
            return
        run_task(self.args)
