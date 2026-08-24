# # import  os
# # import re
# # path=os.getcwd()
# # path_father=os.path.dirname(path)
# # path_config=os.path.join(path_father,'config')
# # path_list=os.listdir(path_config)
# # pattern=re.compile(r'napcat_(\d+).json')
# # for path in path_list:
# #     match=pattern.search(path)
# #     if match:
# #         uid=match.group(1)
# #         print(uid,type(uid))
# #工作空间 会话 权限
# #/workspace=xxx 会话=xxx 权限=xxx
# # import re
# #
# # text = r'/workspace=C:\Users\Public\Documents\QQChatExporter\live-capture\sample session= sandbox=read-only'
# #
# # # 正则只编译一次，放循环外面
# # workspace_pattern = re.compile(r'^workspace=(.+)$')
# # sandbox_pattern = re.compile(r'^sandbox=(.+)$')
# # session_pattern = re.compile(r'^session=(.+)$')
# #
# # if text.startswith('/'):
# #     text = text[1:]
# #     # 用split()不带参数：自动分割任意数量空白，过滤空字符串
# #     parts = text.split()
# #
# #     workspace = None
# #     session = None
# #     sandbox = None
# #
# #     for item in parts:
# #         m_work = workspace_pattern.match(item)
# #         m_sand = sandbox_pattern.match(item)
# #         m_sess = session_pattern.match(item)
# #
# #         if m_work:
# #             workspace = m_work.group(1)
# #         if m_sand:
# #             val = m_sand.group(1)
# #             # 全部使用普通英文减号 -
# #             if val in ['read-only', 'workspace-write', 'danger-full-access']:
# #                 sandbox = val
# #         if m_sess:
# #             session = m_sess.group(1)
# #
# #     print("workspace =", workspace)
# #     print("sandbox   =", sandbox)
# #     print("session   =", session)
#
#
# # import requests
# #
# # url = "http://127.0.0.1:3000/get_login_info"
# #
# # try:
# #     resp = requests.get(url, timeout=5)
# #     resp.raise_for_status() # 如果http错误(404/500)抛异常
# #     print(resp.status_code)
# #     print(resp.json(),type(resp.json())) # 返回json直接解析
# # except requests.exceptions.ConnectionError:
# #     print("❌连接失败，服务没启动/端口没监听")
# # except Exception as e:
# # #     print("异常：", e)
# # import time
# # import requests
# # def fetch_url(url):
# #     '''模拟一个耗时的网络请求'''
# #     print(f'开始获取:{url}')
# #     time.sleep(2)
# #     print(f'完成获取')
# #     return f'来自{url}的数据'
# # def main_sync():
# #     urls=['help1','help2','help3']
# #     results = []
# #     start=time.time()
# #     for url in urls:
# #         result=fetch_url(url)
# #         results.append(result)
# #         end=time.time()
# #     print(f'总耗时为{end-start}')
# #     print(f'结果是{results}')
# # if __name__ == '__main__':
# #     main_sync()
# import  asyncio
# import aiohttp
# import time
# async def fetch_url_async(session,url):
#     '''
#     模拟一个网络请求(异步)
#     '''
#     async with session.get(url) as response:
#         await asyncio.sleep(2)
#         text = await response.text()
#         print(f'完成异步操作:{url}')
#         return f'来自{url},(长度{len(text)})'
# async def main_async():
#     urls=['https://www8.baidu.com/s','https://www.runoob.com/','https://hello-agents.datawhale.cc/#/./README']
#     async with aiohttp.ClientSession() as session:
#         # 为每个url创建一个任务(Task)
#         tasks=[]
#         for url in urls:
#             task=asyncio.create_task(fetch_url_async(session,url))
#             tasks.append(task)
#             print('所有任务已创建,开始并发执行...')
#         results = await asyncio.gather(*tasks)
#         return results
# if __name__ == '__main__':
#     start = time.time()
#     final_results=asyncio.run(main_async())
#     end = time.time()
#     print(f'\n异步版本总消耗时长为:{end-start}秒')
#     for res in final_results:
#         print(res)
# import asyncio
# import time
#
#
# async def say_hello():
#     print('hello')
#     await asyncio.sleep(1)
#     print('world')
# async def say_goodbye():
#     print('goodbye')
#     await asyncio.sleep(1)
#     print('bye')
# async def main():
#     task1=asyncio.create_task(say_hello())
#     task2=asyncio.create_task(say_goodbye())
#     await asyncio.gather(task1, task2)
# if __name__ == '__main__':
#     start = time.time()
#     asyncio.run(main())
#     end = time.time()
#     print(end - start)
# import asyncio
# async def long_task():
#     await asyncio.sleep(10)
#     print('Task finished')
# async def main():
#     try:
#         await asyncio.wait_for(long_task(), timeout=5)
#     except asyncio.TimeoutError:
#         print("task timed out")
# asyncio.run(main())
import asyncio
