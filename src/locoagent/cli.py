"""命令行入口。

这个模块负责把“用户怎么启动 locoagent”翻译成 runtime 能理解的对象：
解析参数、挑模型后端、构建工作区快照、恢复或新建 session，
最后进入 one-shot 或交互式循环。
"""
from .llm import ask_model
def main():
    usr_input = input("locoagent> ")
    response = ask_model(usr_input)
    print(response)

if __name__ == "__main__":
    main()