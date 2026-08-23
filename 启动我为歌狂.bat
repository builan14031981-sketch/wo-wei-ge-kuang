@echo off
chcp 65001 >nul
title 我为歌狂 An1.0
cd /d "%~dp0"
start pythonw main.py
exit
