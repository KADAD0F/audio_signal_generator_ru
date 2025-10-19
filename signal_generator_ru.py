#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import platform
import subprocess
import time
import shutil
import wave
import csv
import re
import threading

# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================================================

def sanitize_filename(name: str) -> str:
    # Удаляем или заменяем недопустимые символы
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name.strip())
    name = name.rstrip('. ')  # Windows не позволяет точку или пробел в конце
    if not name:
        return "output"
    return name[:255]  # Ограничение длины имени файла

def is_yes(user_input: str) -> bool:
    """
    Проверяет, является ли ввод пользователя утвердительным.
    Поддерживает английские и русские варианты ('y', 'yes', 'да', 'д').
    """
    return user_input.strip().lower() in ('y', 'yes', 'да', 'д')

def is_termux() -> bool:
    """
    Определяет, запущен ли скрипт в Termux (Android-терминал).
    Termux использует особый путь к домашней директории.
    """
    return 'com.termux' in os.environ.get('HOME', '')

def check_internet() -> bool:
    """
    Проверяет наличие интернета с помощью ping до известных хостов.
    Возвращает True, если хотя бы один хост отвечает.
    """
    hosts = ['yandex.ru', 'google.com']
    for host in hosts:
        try:
            # Выбор параметра в зависимости от ОС: -n для Windows, -c для Unix
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', host]
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            if result.returncode == 0:
                return True
        except (subprocess.SubprocessError, OSError, TimeoutError):
            continue
    return False

def check_ffmpeg() -> bool:
    """
    Проверяет, установлен ли ffmpeg и доступен ли он для вызова из текущего окружения.
    
    Сначала выполняется поиск исполняемого файла 'ffmpeg' (или 'ffmpeg.exe' на Windows)
    в путях, перечисленных в переменной окружения PATH, с помощью shutil.which().
    Если файл найден — запускается команда 'ffmpeg -version' для подтверждения,
    что программа действительно исполняема и не повреждена.
    
    Функция устойчива к ошибкам запуска, зависаниям и различиям между ОС
    (включая Windows, где исполняемые файлы имеют расширение .exe).
    
    Возвращает True, если ffmpeg найден и успешно отвечает на запрос версии;
    в противном случае — False.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False

    try:
        # Запускаем ffmpeg с ключом -version и подавляем весь ввод-вывод
        # stdin=DEVNULL предотвращает блокировку в случае неожиданного ожидания ввода
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=5  # 5 секунд достаточно даже на слабых системах
        )
        # Успешный запуск означает возврат кода 0
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        # Любая ошибка выполнения (включая отсутствие прав, повреждение бинарника и т.п.)
        # интерпретируется как недоступность ffmpeg
        return False

def determine_output_directory() -> str:
    """
    Определяет директорию для сохранения файлов с учётом прав доступа в Termux.
    - В Termux по умолчанию пытается использовать ~/storage/shared.
    - Если запись невозможна — предлагает:
        a) выполнить termux-setup-storage и повторить попытку;
        b) использовать локальную директорию ($HOME).
    - Вне Termux возвращает текущую рабочую директорию.
    """
    if not is_termux():
        return os.getcwd()

    home = os.environ.get('HOME', '')
    if not home:
        print("⚠️  Не удалось определить домашнюю директорию. Используется текущая.")
        return os.getcwd()

    shared_dir = os.path.join(home, 'storage', 'shared')
    local_dir = home

    # Проверка возможности записи в shared-директорию
    def can_write_to(path: str) -> bool:
        if not os.path.exists(path):
            return False
        test_file = os.path.join(path, '.write_test_ffmpeg_signal')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            return True
        except (OSError, IOError):
            return False

    if can_write_to(shared_dir):
        print(f"📁 Termux: используется общая папка — {shared_dir}")
        return shared_dir

    print(f"❌ Нет прав на запись в {shared_dir}")
    print("\nВ Termux для доступа к общему хранилищу требуется разрешение.")

    while True:
        choice = input("Попробовать запросить разрешение через termux-setup-storage? (y/n): ")
        if is_yes(choice):
            print("Выполняется termux-setup-storage... Следуйте инструкциям на экране.")
            print("После завершения нажмите Enter, чтобы продолжить.")
            try:
                subprocess.run(['termux-setup-storage'], check=True)
            except (subprocess.SubprocessError, FileNotFoundError):
                print("⚠️  Не удалось запустить termux-setup-storage.")
                break

            input()  # Ждём подтверждения от пользователя

            if can_write_to(shared_dir):
                print(f"✅ Доступ получен. Файлы будут сохранены в: {shared_dir}")
                return shared_dir
            else:
                print("❌ Доступ не предоставлен. Повторите попытку или выберите локальное сохранение.")
                continue

        if choice.strip().lower() in ('n', 'no', 'нет', 'н'):
            print(f"📁 Используется локальная директория Termux: {local_dir}")
            return local_dir

        print("Пожалуйста, введите 'y' или 'n'.")

    # Резервный вариант, если цикл прерван без возврата
    print(f"📁 Резерв: сохранение в локальную директорию {local_dir}")
    return local_dir

def confirm_overwrite(filepath: str) -> str:
    """
    Проверяет, существует ли файл по указанному пути.
    Если файл существует:
      - спрашивает пользователя, перезаписать ли его;
      - если пользователь отказывается — генерирует новое имя с суффиксом _1, _2, ...
    Возвращает путь, по которому можно безопасно сохранить файл без перезаписи.
    """
    if not os.path.exists(filepath):
        return filepath

    print(f"⚠️  Файл уже существует: {filepath}")
    choice = input("Перезаписать? (y/n): ").strip().lower()
    if is_yes(choice):
        return filepath

    # Пользователь отказался → генерируем уникальное имя
    base, ext = os.path.splitext(filepath)
    counter = 1
    while True:
        new_path = f"{base}_{counter}{ext}"
        if not os.path.exists(new_path):
            print(f"📁 Используется новое имя: {new_path}")
            return new_path
        counter += 1

# ==============================================================================
# УСТАНОВКА ЗАВИСИМОСТЕЙ
# ==============================================================================

def install_package_heavy(package_name: str) -> bool:
    """
    Устанавливает "тяжёлый" пакет (например, jax, librosa) с прогресс-баром.
    Отображает процент завершения или анимацию загрузки.
    Корректно обрабатывает прерывание через Ctrl+C.
    """
    print(f"\nУстановка {package_name}... ", end='', flush=True)
    start_time = time.time()
    install_cmd = [sys.executable, '-m', 'pip', 'install', package_name]

    process = subprocess.Popen(
        install_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )

    bar_length = 30
    last_update = 0
    spinner = '|/-\\'

    def parse_line(line: str):
        """Извлекает процент из строки вывода pip (если есть)."""
        if '%' in line:
            parts = line.split()
            for part in parts:
                if part.endswith('%'):
                    try:
                        return float(part.rstrip('%'))
                    except ValueError:
                        continue
        return None

    try:
        # Чтение вывода установки в реальном времени
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            current_time = time.time()
            elapsed = current_time - start_time

            # Ограничиваем частоту обновления интерфейса
            if current_time - last_update < 0.1:
                continue
            last_update = current_time

            percent = parse_line(line)

            if percent is not None:
                filled = int(bar_length * percent / 100)
                bar = '█' * filled + ' ' * (bar_length - filled)
                print(f"\rУстановка {package_name}... [{bar}] {percent:.0f}% ({elapsed:.0f}s) ",
                      end='', flush=True)
            else:
                spin_char = spinner[int(elapsed) % len(spinner)]
                print(f"\rУстановка {package_name}... {spin_char} ({elapsed:.0f}s) ",
                      end='', flush=True)

        process.wait()

    except KeyboardInterrupt:
        print("\n\n⚠️  Установка прервана пользователем (Ctrl+C). Завершение процесса pip...")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return False

    if process.returncode != 0:
        print(f"\n\n❌ Установка {package_name} завершилась с ошибкой.")
        print(f"Код ошибки: {process.returncode}")
        print("Попробуйте установить вручную:")
        print(f"  {sys.executable} -m pip install {package_name}")
        return False

    print(f"\n\n✅ {package_name} успешно установлен!")
    return True

def install_library(package_name: str, is_heavy: bool = False) -> bool:
    """
    Универсальная функция установки библиотеки.
    Запрашивает подтверждение у пользователя и выбирает способ установки.
    """
    if not check_internet():
        print(f"❌ Ошибка: отсутствует интернет. Невозможно установить {package_name}.")
        return False

    install = input(f"{package_name} не установлен. Установить? (y/n): ")
    if not is_yes(install):
        print(f"Установка {package_name} отменена.")
        return False

    if is_heavy and is_termux():
        print(f"\n⚠️  Termux: установка {package_name} может занять 10–60 минут!")
        print("Рассмотрите установку через pkg (если доступно).")
        print("Продолжаем через pip...")

    if is_heavy:
        return install_package_heavy(package_name)

    try:
        print(f"Установка {package_name}...")
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', package_name
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✅ {package_name} установлен.")
        return True
    except Exception as e:
        print(f"Ошибка установки {package_name}: {e}")
        return False

def get_library(import_func, package_names: list, is_heavy: bool = False):
    """
    Пытается импортировать библиотеку. Если не получается — устанавливает её.
    Поддерживает список альтернативных пакетов.
    """
    try:
        return import_func()
    except ImportError:
        pass

    for package in package_names:
        if install_library(package, is_heavy):
            try:
                return import_func()
            except ImportError:
                continue

    print(f"\n❌ Не удалось установить ни один из пакетов: {', '.join(package_names)}")
    print("Попробуйте вручную:")
    for p in package_names:
        print(f"  pip install {p}")
    sys.exit(1)

# ==============================================================================
# ПОЛУЧЕНИЕ ОСНОВНЫХ БИБЛИОТЕК
# ==============================================================================

def get_numpy_or_alternative():
    """
    Пытается импортировать numpy. Если не получается — пробует jax.numpy.
    Обе библиотеки предоставляют совместимый API для работы с массивами.
    """
    def try_numpy():
        import numpy as np
        return np

    def try_jax():
        import jax.numpy as jnp
        return jnp

    try:
        return try_numpy()
    except ImportError:
        pass

    if install_library('jax', is_heavy=True):
        try:
            return try_jax()
        except ImportError:
            pass

    print("\n❌ Не удалось установить ни numpy, ни jax.")
    sys.exit(1)

def get_audio_library():
    """
    Возвращает обёртку для работы с аудио.
    Поддерживает pydub (для MP3), librosa и soundfile (для чтения/анализа).
    """
    def try_pydub():
        from pydub import AudioSegment
        return AudioSegment

    def try_librosa():
        import librosa
        class LibrosaWrapper:
            @staticmethod
            def from_file(path):
                y, sr = librosa.load(path, sr=None)
                return (y, sr)
        return LibrosaWrapper

    def try_soundfile():
        import soundfile as sf
        class SoundfileWrapper:
            @staticmethod
            def from_file(path):
                data, samplerate = sf.read(path)
                return (data, samplerate)
        return SoundfileWrapper

    try:
        aud = try_pydub()
        if not check_ffmpeg():
            print("\n⚠️  ffmpeg не найден. pydub может не работать.")
        return aud
    except ImportError:
        pass

    if install_library('librosa', is_heavy=True):
        try:
            return try_librosa()
        except ImportError:
            pass

    if install_library('soundfile', is_heavy=False):
        try:
            return try_soundfile()
        except ImportError:
            pass

    print("\n❌ Не удалось установить ни одну аудиобиблиотеку.")
    sys.exit(1)

def get_plotting_library():
    """
    Возвращает библиотеку для визуализации: matplotlib, plotly или plotext.
    Все обёрнуты в единый интерфейс.
    """
    def try_matplotlib():
        import matplotlib
        matplotlib.use('Agg')  # Без GUI — для серверов и Termux
        import matplotlib.pyplot as plt
        return plt

    def try_plotly():
        import plotly.graph_objects as go
        class PlotlyWrapper:
            def plot(self, x, y, title=""):
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=x, y=y))
                fig.update_layout(title=title)
                fig.show()
        return PlotlyWrapper()

    def try_plotext():
        import plotext as plt
        class PlotextWrapper:
            def plot(self, x, y, title=""):
                plt.clear_data()
                plt.plot(x, y)
                plt.title(title)
                plt.show()
        return PlotextWrapper()

    try:
        return try_matplotlib()
    except ImportError:
        pass

    if install_library('plotly', is_heavy=False):
        try:
            return try_plotly()
        except ImportError:
            pass

    if install_library('plotext', is_heavy=False):
        try:
            return try_plotext()
        except ImportError:
            pass

    print("\n❌ Не удалось установить ни одну библиотеку для графиков.")
    sys.exit(1)

# ==============================================================================
# ВВОД ДАННЫХ ОТ ПОЛЬЗОВАТЕЛЯ
# ==============================================================================

def get_input(prompt, default=None, min_val=None, max_val=None, type_func=float):
    """
    Универсальная функция ввода числа с валидацией.
    Поддерживает диапазоны, типы (int/float), значения по умолчанию.
    """
    while True:
        hint = f" [{min_val}-{max_val}]" if min_val is not None and max_val is not None else ""
        if default is not None:
            hint += f" (по умолчанию: {default})"
        user_input = input(f"{prompt}{hint}: ")
        if user_input == '' and default is not None:
            return default

        if type_func is float:
            user_input = user_input.replace(',', '.')

        try:
            value = type_func(user_input)
            if min_val is not None and value < min_val:
                print(f"Ошибка: значение должно быть не меньше {min_val}.")
                continue
            if max_val is not None and value > max_val:
                print(f"Ошибка: значение должно быть не больше {max_val}.")
                continue
            return value
        except ValueError:
            print("Ошибка: введите корректное значение.")

def get_disk_space(path):
    """
    Возвращает свободное место на диске в байтах.
    Используется для предупреждения о нехватке места.
    """
    try:
        total, used, free = shutil.disk_usage(path)
        return free
    except Exception:
        return None

# ==============================================================================
# ОБРАБОТКА СИГНАЛОВ
# ==============================================================================

def normalize_signal(np, signal, max_amplitude=0.99):
    """
    Нормализует сигнал так, чтобы его максимальная амплитуда не превышала max_amplitude.
    Предотвращает клиппинг при сохранении в WAV/MP3.
    """
    max_abs = np.max(np.abs(signal))
    if max_abs > max_amplitude:
        return signal / max_abs * max_amplitude
    return signal

def generate_sin(np, duration, sample_rate, freq, amplitude):
    """Генерирует синусоидальный сигнал."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    return amplitude * np.sin(2 * np.pi * freq * t)

def generate_am(np, duration, sample_rate, carrier_freq, mod_freq, mod_depth, amplitude):
    """Генерирует амплитудно-модулированный сигнал."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    mod = 1 + mod_depth * np.sin(2 * np.pi * mod_freq * t)
    return amplitude * mod * np.sin(2 * np.pi * carrier_freq * t)

def generate_pulse(np, duration, sample_rate, pulse_freq, duty_cycle, amplitude):
    """Генерирует прямоугольный импульсный сигнал (меандр с заданной скважностью)."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    period = 1 / pulse_freq
    phase = (t % period) / period
    return amplitude * np.where(phase < duty_cycle, 1, -1)

def generate_noise(np, duration, sample_rate, amplitude, noise_type='uniform'):
    """Генерирует белый шум: равномерный или нормальный."""
    num_samples = int(sample_rate * duration)
    if noise_type == 'uniform':
        noise = np.random.uniform(-amplitude, amplitude, num_samples)
    elif noise_type == 'normal':
        noise = np.random.normal(0, amplitude, num_samples)
    else:
        raise ValueError("Неверный тип шума")

    return normalize_signal(np, noise, amplitude)

def generate_chm(np, duration, sample_rate, start_freq, end_freq, chm_type, amplitude):
    """
    Генерирует ЧМ-сигнал (частотная модуляция) с разными законами:
    - linear: линейная
    - quadratic: квадратичная
    - hyperbolic: гиперболическая
    """
    if duration <= 0:
        raise ValueError("Длительность должна быть положительной")
    if start_freq <= 0 or end_freq <= 0:
        raise ValueError("Частоты должны быть положительными для гиперболической ЧМ")

    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    T = duration

    if chm_type == 'linear':
        phase = 2 * np.pi * (start_freq * t + (end_freq - start_freq) * t**2 / (2 * T))
    elif chm_type == 'quadratic':
        phase = 2 * np.pi * (start_freq * t + (end_freq - start_freq) * t**3 / (3 * T**2))
    elif chm_type == 'hyperbolic':
        if abs(end_freq - start_freq) < 1e-12:
            phase = 2 * np.pi * start_freq * t
        else:
            inv_f0 = 1.0 / start_freq
            inv_f1 = 1.0 / end_freq
            a = (inv_f1 - inv_f0) / T
            b = inv_f0
            denom = a * t + b
            if np.any(denom <= 0):
                raise ValueError("Некорректные параметры: мгновенная частота становится отрицательной или бесконечной")
            if abs(a) < 1e-15:
                phase = 2 * np.pi * start_freq * t
            else:
                phase = 2 * np.pi * (np.log(denom) - np.log(b)) / a
    else:
        raise ValueError("Неверный тип ЧМ")

    return amplitude * np.sin(phase)

# ==============================================================================
# ПАРАМЕТРЫ И ГЕНЕРАЦИЯ СИГНАЛОВ
# ==============================================================================

def get_signal_parameters(np, signal_type, sample_rate, stereo=False):
    """
    Запрашивает у пользователя параметры сигнала в зависимости от его типа.
    Поддерживает стерео-режим (разные параметры для левого/правого канала).
    """
    params = {}
    if stereo:
        params['stereo'] = True
        print("\nНастройки для левого канала:")

    if signal_type == 'sin':
        params['freq'] = get_input("Частота", min_val=0.0, max_val=sample_rate/2)
        params['amplitude'] = get_input("Амплитуда", min_val=0.0, max_val=1.0)
    elif signal_type == 'am':
        params['carrier_freq'] = get_input("Несущая частота", min_val=0.0, max_val=sample_rate/2)
        params['mod_freq'] = get_input("Частота модуляции", min_val=0.0, max_val=sample_rate/2)
        params['mod_depth'] = get_input("Глубина модуляции", min_val=0.0, max_val=1.0)
        params['amplitude'] = get_input("Амплитуда", min_val=0.0, max_val=1.0)
    elif signal_type == 'pulse':
        params['pulse_freq'] = get_input("Частота импульсов", min_val=0.0, max_val=sample_rate/2)
        params['duty_cycle'] = get_input("Скважность", min_val=0.0, max_val=1.0)
        params['amplitude'] = get_input("Амплитуда", min_val=0.0, max_val=1.0)
    elif signal_type == 'noise':
        noise_map = {
            '1': 'uniform', 'uniform': 'uniform',
            '2': 'normal', 'normal': 'normal'
        }
        noise_type_choice = input("Тип шума (1/uniform, 2/normal) [1]: ").strip().lower()
        params['noise_type'] = noise_map.get(noise_type_choice, 'uniform')
        params['amplitude'] = get_input("Амплитуда", min_val=0.0, max_val=1.0)
    elif signal_type == 'chm':
        params['start_freq'] = get_input("Начальная частота", min_val=0.0, max_val=sample_rate/2)
        params['end_freq'] = get_input("Конечная частота", min_val=0.0, max_val=sample_rate/2)
        print("\nДоступные подтипы ЧМ:")
        print("1. linear   - Линейная ЧМ")
        print("2. quadratic- Квадратичная ЧМ")
        print("3. hyperbolic- Гиперболическая ЧМ")
        chm_map = {
            '1': 'linear', 'linear': 'linear',
            '2': 'quadratic', 'quadratic': 'quadratic',
            '3': 'hyperbolic', 'hyperbolic': 'hyperbolic'
        }
        chm_type_choice = input("Выберите подтип (1-3 или название): ").strip().lower()
        params['chm_type'] = chm_map.get(chm_type_choice, 'linear')
        params['amplitude'] = get_input("Амплитуда", min_val=0.0, max_val=1.0)

    if stereo and signal_type != 'multi':
        print("\nНастройки для правого канала (оставьте пустым для копирования левого канала):")
        right_params = get_signal_parameters(np, signal_type, sample_rate, stereo=False)
        params['right_params'] = right_params

    return params

def generate_signal(np, signal_type, duration, sample_rate, channels, **kwargs):
    """
    Генерирует одноканальный или стерео-сигнал указанного типа.
    При стерео — может использовать разные параметры для каналов.
    """
    if signal_type == 'sin':
        signal = generate_sin(np, duration, sample_rate, kwargs['freq'], kwargs['amplitude'])
    elif signal_type == 'am':
        signal = generate_am(np, duration, sample_rate, kwargs['carrier_freq'],
                          kwargs['mod_freq'], kwargs['mod_depth'], kwargs['amplitude'])
    elif signal_type == 'pulse':
        signal = generate_pulse(np, duration, sample_rate, kwargs['pulse_freq'],
                             kwargs['duty_cycle'], kwargs['amplitude'])
    elif signal_type == 'noise':
        signal = generate_noise(np, duration, sample_rate, kwargs['amplitude'], kwargs['noise_type'])
    elif signal_type == 'chm':
        signal = generate_chm(np, duration, sample_rate, kwargs['start_freq'],
                           kwargs['end_freq'], kwargs['chm_type'], kwargs['amplitude'])
    else:
        raise ValueError("Неверный тип сигнала")

    signal = normalize_signal(np, signal)

    if channels == 2:
        if 'stereo' in kwargs and kwargs['stereo'] and 'right_params' in kwargs:
            right_signal = generate_signal(np, signal_type, duration, sample_rate, 1, **kwargs['right_params'])
            right_signal = normalize_signal(np, right_signal)
            return np.column_stack((signal, right_signal))
        else:
            return np.column_stack((signal, signal))

    return signal

def generate_multi(np, duration, sample_rate, channels):
    """
    Режим 'multi': пользователь добавляет несколько сигналов,
    которые суммируются в один выходной сигнал.
    Поддерживает стерео.
    """
    signals = []
    stereo_mode = channels == 2

    # Допустимые типы сигналов
    valid_types = ['sin', 'am', 'pulse', 'noise', 'chm']
    # Сопоставление цифр → типы
    digit_to_type = {
        '1': 'sin',
        '2': 'am',
        '3': 'pulse',
        '4': 'noise',
        '5': 'chm'
    }

    def resolve_signal_type(user_input: str):
        """Преобразует ввод (цифру, полное или сокращённое имя) в корректный тип сигнала."""
        inp = user_input.strip().lower()
        if not inp:
            return None
        # Сначала проверяем цифры
        if inp in digit_to_type:
            return digit_to_type[inp]
        # Затем пробуем найти совпадение по префиксу
        matches = [t for t in valid_types if t.startswith(inp)]
        if len(matches) == 1:
            return matches[0]
        # Если неоднозначно или нет совпадений — None
        return None

    print("\nДобавление сигналов (оставьте пустым для завершения):")
    while True:
        signal_type_input = input("Тип сигнала (sin, am, pulse, noise, chm): ").strip()
        if not signal_type_input:
            break

        signal_type = resolve_signal_type(signal_type_input)
        if signal_type is None:
            print("Неверный тип. Допустимые: sin, am, pulse, noise, chm (или 1–5, или сокращения, например 'puls', 'noi', 'ch')")
            continue

        is_stereo = False
        if stereo_mode:
            stereo_choice = input("Создать разные сигналы для левого и правого канала? (y/n): ")
            is_stereo = is_yes(stereo_choice)
        try:
            params = get_signal_parameters(np, signal_type, sample_rate, is_stereo)
            params['stereo'] = is_stereo
            signal = generate_signal(np, signal_type, duration, sample_rate, channels, **params)
            signals.append(signal)
            print(f"Сигнал {signal_type} добавлен.\n")
        except Exception as e:
            print(f"Ошибка при генерации сигнала: {e}")
            continue

    if not signals:
        raise ValueError("Не добавлено ни одного сигнала")

    if channels == 1:
        combined = np.sum(signals, axis=0)
    else:
        left = np.sum([s[:, 0] for s in signals], axis=0)
        right = np.sum([s[:, 1] for s in signals], axis=0)
        combined = np.column_stack((left, right))

    combined = normalize_signal(np, combined)
    max_abs = np.max(np.abs(combined))
    if max_abs > 0.99:
        print(f"Сигнал нормализован (макс. амплитуда: {max_abs:.4f})")

    return combined

# ==============================================================================
# СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
# ==============================================================================

def save_wav(np, filename, sample_rate, data, channels):
    """
    Сохраняет сигнал в WAV-файл (16-bit PCM).
    
    Поддерживает numpy и jax.numpy.
    Обрабатывает как моно (1D), так и стерео (2D: (N, 2)) сигналы.
    
    Args:
        np: библиотека для работы с массивами (numpy или jax.numpy)
        filename: путь к выходному файлу
        sample_rate: частота дискретизации
        data: аудиоданные (1D для моно, 2D с shape=(N, 2) для стерео)
        channels: количество каналов (1 или 2)
    """
    # Проверка входных данных
    if channels not in (1, 2):
        raise ValueError("Количество каналов должно быть 1 или 2")
    
    # Проверка типа данных
    if not hasattr(data, 'dtype') or data.dtype.kind not in ('f', 'i'):
        raise TypeError("Данные должны быть числового типа")
    
    # Защитная нормализация
    data = normalize_signal(np, data, max_amplitude=0.99)
    
    # Обработка формы данных
    if data.ndim == 2:
        if data.shape[1] != channels:
            raise ValueError(f"Ожидалось {channels} каналов, получено {data.shape[1]}")
        # Интерливинг: (N, 2) → [L0, R0, L1, R1, ...]
        data_flat = data.flatten(order='C')  # C-order = row-major = L, R, L, R...
    elif data.ndim == 1:
        if channels != 1:
            raise ValueError("1D-сигнал, но указано channels != 1")
        data_flat = data
    else:
        raise ValueError("Сигнал должен быть 1D или 2D массивом")
    
    # Проверка, что данные содержат числовые значения
    if not np.issubdtype(data_flat.dtype, np.number):
        data_flat = data_flat.astype(np.float32)
    
    # Масштабирование в 16-битный диапазон с полным использованием диапазона
    # 32767.5 позволяет более точно использовать весь диапазон [-32768, 32767]
    scaled = data_flat * 32767.5
    clipped = np.clip(scaled, -32768, 32767)
    rounded = np.round(clipped)
    data_int16 = rounded.astype(np.int16)
    
    # Проверка на NaN и Inf
    if hasattr(np, 'isnan') and np.isnan(data_int16).any():
        raise ValueError("Данные содержат NaN значения")
    if hasattr(np, 'isinf') and np.isinf(data_int16).any():
        raise ValueError("Данные содержат бесконечные значения")
    
    # Запись в файл
    with wave.open(filename, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)  # 16 бит = 2 байта
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(data_int16.tobytes())
    
    # Проверка успешной записи
    if not os.path.exists(filename) or os.path.getsize(filename) == 0:
        raise IOError(f"Не удалось записать файл {filename}")

def save_csv(filename, data, channels):
    """Сохраняет сигнал в CSV для анализа в Excel и т.п."""
    try:
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if channels == 1:
                writer.writerow(['index', 'value'])
                for i, value in enumerate(data):
                    writer.writerow([i, value])
            else:
                writer.writerow(['index', 'left', 'right'])
                for i, (left, right) in enumerate(data):
                    writer.writerow([i, left, right])
    except Exception as e:
        print(f"Предупреждение: не удалось сохранить CSV: {e}")

def save_mp3(np, AudioSegment, filename, sample_rate, data, channels):
    """Сохраняет сигнал в MP3 через pydub и ffmpeg с полной обработкой ошибок."""
    try:
        # Нормализация сигнала
        data = normalize_signal(np, data, max_amplitude=0.99)
        
        # Обработка стерео/моно данных
        if data.ndim == 2:
            if data.shape[1] != channels:
                raise ValueError(f"Ожидалось {channels} каналов, получено {data.shape[1]}")
            # Интерливинг для стерео (L1, R1, L2, R2, ...)
            data_flat = data.flatten(order='C')
        else:
            if channels != 1:
                raise ValueError(f"Ожидалось 1 канал, получено {channels}")
            data_flat = data
        
        # Проверка размерности данных
        if data_flat.ndim != 1:
            raise ValueError("Данные должны быть одномерным массивом после обработки")
        
        # Преобразование в 16-битный формат
        # Используем правильное преобразование с учетом диапазона
        data_int16 = (data_flat * 32767.0).astype(np.int16)
        
        # Создание аудио сегмента
        audio = AudioSegment(
            data_int16.tobytes(),
            frame_rate=sample_rate,
            sample_width=2,
            channels=channels
        )
        
        # Сохранение в MP3
        audio.export(filename, format='mp3')
        return True
    except Exception as e:
        # Подробное логирование ошибки
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Ошибка при сохранении MP3: {str(e)}")
        print(f"Детали ошибки:\n{error_details}")
        return False

def save_visualization(np, signal, output_dir, base_filename):
    """
    Сохраняет график сигнала в PNG/SVG/PDF.
    Для ускорения отображает только первые 10 000 отсчётов.
    """
    plt = get_plotting_library()
    if plt is None:
        return False

    try:
        plt.figure(figsize=(12, 5))

        if signal.ndim > 1:
            n_samples = min(10000, len(signal))
            print(f"Отображаются первые {n_samples} отсчётов из {len(signal)} для ускорения отрисовки")
            plt.plot(signal[:n_samples, 0], 'b', label='Левый канал')
            plt.plot(signal[:n_samples, 1], 'r', label='Правый канал')
            plt.legend()
        else:
            n_samples = min(10000, len(signal))
            print(f"Отображаются первые {n_samples} отсчётов из {len(signal)} для ускорения отрисовки")
            plt.plot(signal[:n_samples])

        plt.title('Сгенерированный сигнал')
        plt.xlabel('Отсчеты')
        plt.ylabel('Амплитуда')
        plt.grid(True, linestyle='--', alpha=0.7)

        formats = ['png', 'svg', 'pdf']
        fmt = input(f"Формат визуализации ({'/'.join(formats)}) [по умолчанию png]: ").strip().lower()
        fmt = fmt if fmt in formats else 'png'
        viz_path = os.path.join(output_dir, f"{base_filename}_visualization.{fmt}")

        plt.savefig(viz_path, bbox_inches='tight', dpi=300)
        plt.close()
        print(f"✅ Визуализация сохранена: {viz_path}")
        return True
    except Exception as e:
        print(f"Ошибка при создании визуализации: {e}")
        return False

def save_spectrogram_video(np, signal, sample_rate, output_dir, base_filename, channels, hop_length=512, n_fft=2048):
    """
    Создаёт видео спектрограммы сигнала.
    Поддерживает моно и стерео (обрабатывает только левый канал или среднее).
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import subprocess
        import os
        import tempfile
        import shutil

        # Подготовка сигнала: моно
        if signal.ndim == 2:
            # Берём среднее по каналам или только левый
            mono_signal = np.mean(signal, axis=1)
        else:
            mono_signal = signal

        # STFT
        from numpy.fft import rfft, rfftfreq
        window = np.hanning(n_fft)
        num_frames = (len(mono_signal) - n_fft) // hop_length + 1
        if num_frames <= 0:
            raise ValueError("Сигнал слишком короткий для анализа")

        # Создаём временную папку для кадров
        with tempfile.TemporaryDirectory() as tmpdir:
            print(f"Генерация {num_frames} кадров спектрограммы...")
            for i in range(num_frames):
                start = i * hop_length
                frame = mono_signal[start:start + n_fft]
                if len(frame) < n_fft:
                    frame = np.pad(frame, (0, n_fft - len(frame)), mode='constant')
                windowed = frame * window
                spectrum = np.abs(rfft(windowed))
                freqs = rfftfreq(n_fft, 1 / sample_rate)

                # Ограничим частоты до Nyquist
                max_freq_idx = np.argmax(freqs > sample_rate / 2)
                if max_freq_idx == 0:
                    max_freq_idx = len(freqs)
                spectrum = spectrum[:max_freq_idx]
                freqs = freqs[:max_freq_idx]

                # Логарифмическая шкала (дБ)
                spectrum_db = 20 * np.log10(spectrum + 1e-9)
                spectrum_db = np.clip(spectrum_db, spectrum_db.max() - 80, None)

                # Рисуем кадр
                plt.figure(figsize=(10, 4))
                plt.plot(freqs, spectrum_db, color='cyan')
                plt.ylim(spectrum_db.max() - 80, spectrum_db.max())
                plt.xlim(0, sample_rate / 2)
                plt.xlabel('Частота (Гц)')
                plt.ylabel('Амплитуда (дБ)')
                plt.title(f'Спектрограмма | Время: {i * hop_length / sample_rate:.2f} с')
                plt.grid(True, linestyle='--', alpha=0.5)
                plt.tight_layout()
                frame_path = os.path.join(tmpdir, f'frame_{i:06d}.png')
                plt.savefig(frame_path, dpi=100)
                plt.close()

            # Собираем видео через ffmpeg
            video_path = os.path.join(output_dir, f"{base_filename}_spectrogram.mp4")
            cmd = [
                'ffmpeg', '-y',
                '-framerate', '20',
                '-i', os.path.join(tmpdir, 'frame_%06d.png'),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-preset', 'fast',
                '-crf', '23',
                video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode != 0:
                raise RuntimeError("ffmpeg не смог создать видео")

        print(f"✅ Видео спектрограммы сохранено: {video_path}")
        return video_path

    except ImportError as e:
        print(f"❌ Отсутствует зависимость: {e}")
        return None
    except Exception as e:
        print(f"❌ Ошибка при создании видео спектрограммы: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ==============================================================================
def main():
    """
    Главная функция программы.
    Последовательно:
    1. Загружает numpy или альтернативу
    2. Определяет директорию вывода
    3. Запрашивает тип сигнала и параметры
    4. Генерирует сигнал
    5. Сохраняет в выбранных форматах с защитой от перезаписи
    6. (Опционально) сохраняет визуализацию, CSV, спектрограмму
    """
    np = get_numpy_or_alternative()
    if np is None:
        print("Для работы скрипта требуется библиотека для работы с массивами. Скрипт завершен.")
        sys.exit(1)

    # Определение директории сохранения с проверкой прав
    output_dir = determine_output_directory()
    in_termux = is_termux()

    # Вывод справки по типам сигналов
    print("\n" + "="*50)
    print("ДОСТУПНЫЕ ТИПЫ СИГНАЛОВ")
    print("="*50)
    print("1. sin  - Синусоида")
    print("2. am   - Амплитудная модуляция")
    print("3. pulse- Импульсный сигнал")
    print("4. noise- Белый шум")
    print("   • uniform  - Равномерное распределение")
    print("   • normal   - Нормальное распределение")
    print("5. chm  - Частотная модуляция (ЧМ)")
    print("   • linear   - Линейная ЧМ")
    print("   • quadratic- Квадратичная ЧМ")
    print("   • hyperbolic- Гиперболическая ЧМ")
    print("6. multi- Мульти-режим (суммирование сигналов)")
    print("="*50)

    # Выбор типа сигнала
    signal_map = {
        '1': 'sin', 'sin': 'sin',
        '2': 'am', 'am': 'am',
        '3': 'pulse', 'pulse': 'pulse',
        '4': 'noise', 'noise': 'noise',
        '5': 'chm', 'chm': 'chm',
        '6': 'multi', 'multi': 'multi'
    }
    signal_type = input("\nВыберите тип сигнала (1-6 или название): ").strip().lower()
    if signal_type not in signal_map:
        print("Ошибка: неверный выбор типа сигнала")
        return
    signal_type = signal_map[signal_type]
    print(f"Выбран тип: {signal_type}")

    # Ввод основных параметров
    duration = get_input("Длительность сигнала (сек)", min_val=0.001)
    sample_rate = get_input("Частота дискретизации (Гц)", default=44100, min_val=1)
    channels = get_input("Количество каналов (1/2)", default=1, min_val=1, max_val=2, type_func=int)

    # Проверка свободного места
    num_samples = int(duration * sample_rate * channels)
    estimated_size = num_samples * 4  # ~4 байта на float32
    free_space = get_disk_space(output_dir)
    if free_space and free_space < estimated_size * 1.5:
        print(f"\n⚠️  Недостаточно места на диске!")
        print(f"Требуется: {estimated_size / (1024*1024):.1f} МБ")
        print(f"Доступно: {free_space / (1024*1024):.1f} МБ")
        proceed = input("Продолжить? (y/n): ")
        if not is_yes(proceed):
            print("Генерация отменена.")
            return

    if estimated_size > 500 * 1024 * 1024:
        print(f"\n⚠️  Внимание: генерация займет примерно {estimated_size / (1024*1024):.1f} МБ памяти")
        print("Это может вызвать замедление работы или зависание системы.")
        proceed = input("Продолжить? (y/n): ")
        if not is_yes(proceed):
            print("Генерация отменена.")
            return

    # Имя выходного файла
    raw_name = input("Имя выходного файла (без расширения): ")
    output_filename = sanitize_filename(raw_name)

    # --- ГЕНЕРАЦИЯ СИГНАЛА ---
    try:
        if signal_type == 'multi':
            signal = generate_multi(np, duration, sample_rate, channels)
        else:
            params = get_signal_parameters(np, signal_type, sample_rate, channels == 2)
            params['stereo'] = channels == 2
            signal = generate_signal(np, signal_type, duration, sample_rate, channels, **params)

        # Выбор формата сохранения
        print("\nВыберите формат сохранения:")
        print("1. WAV")
        print("2. MP3 (требуется ffmpeg и pydub)")
        print("3. Оба формата")
        format_choice = get_input("Ваш выбор", default=1, min_val=1, max_val=3, type_func=int)
        formats_saved = []
        mp3_saved = False

        # --- Сохранение WAV ---
        if format_choice in [1, 3]:
            output_wav = os.path.join(output_dir, output_filename + ".wav")
            safe_wav = confirm_overwrite(output_wav)
            try:
                save_wav(np, safe_wav, sample_rate, signal, channels)
                formats_saved.append("WAV")
                print(f"\n✅ WAV сохранен в {safe_wav}")
            except Exception as e:
                print(f"❌ Ошибка при сохранении WAV: {e}")
                import traceback
                traceback.print_exc()

        # --- Сохранение MP3 ---
        if format_choice in [2, 3]:
            ffmpeg_available = check_ffmpeg()
            if not ffmpeg_available:
                print("⚠️  ffmpeg не найден. Установите ffmpeg для сохранения в MP3.")
                print("   На Ubuntu: sudo apt install ffmpeg")
                print("   На Windows: https://ffmpeg.org/download.html")
                print("   На macOS: brew install ffmpeg")
                print("   Для Termux: pkg install ffmpeg")
            else:
                try:
                    from pydub import AudioSegment
                    output_mp3 = os.path.join(output_dir, output_filename + ".mp3")
                    safe_mp3 = confirm_overwrite(output_mp3)
                    if save_mp3(np, AudioSegment, safe_mp3, sample_rate, signal, channels):
                        formats_saved.append("MP3")
                        print(f"✅ MP3 сохранен в {safe_mp3}")
                        mp3_saved = True
                    else:
                        print("❌ Не удалось сохранить MP3 файл")
                except ImportError:
                    print("❌ MP3 сохранение невозможно: pydub не установлен")
                    print("   Установите pydub командой: pip install pydub")

            # Если MP3 не сохранился, а выбран только MP3 — предложить WAV
            if not mp3_saved and format_choice == 2:
                save_wav_alt = input("Хотите сохранить в формате WAV вместо MP3? (y/n): ")
                if is_yes(save_wav_alt):
                    output_wav = os.path.join(output_dir, output_filename + ".wav")
                    safe_wav = confirm_overwrite(output_wav)
                    try:
                        save_wav(np, safe_wav, sample_rate, signal, channels)
                        formats_saved.append("WAV")
                        print(f"\n✅ WAV сохранен в {safe_wav}")
                    except Exception as e:
                        print(f"❌ Ошибка при сохранении WAV: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print("❌ MP3 не сохранен, и вы отказались от сохранения в WAV.")

        # --- ДОПОЛНИТЕЛЬНЫЕ ОПЦИИ ДЛЯ ПРОФЕССИОНАЛОВ ---
        print("\nДополнительные опции (enter для пропуска):")
        print("1. Визуализация сигнала (график)")
        print("2. Сохранение CSV (для Excel и анализа)")
        print("3. Неконтролируемая амплитуда (без нормализации)")
        print("4. Видео спектрограммы (экспериментальная функция)")
        print("Важно: Дополнительные настройки могут быть нежелательны для тех, кто не знает что делать. Используйте с умом")
        pro_choice = input("Выберите опции (например, '1 4' для визуализации и спектрограммы): ").strip()
        professional_options = []
        options = pro_choice.split()

        if not options:
            print("Дополнительные экспериментальные опции пропущены.")
        else:
            # Визуализация
            if '1' in options:
                print("\nНастройка визуализации...")
                viz_base = os.path.join(output_dir, output_filename + "_visualization")
                formats = ['png', 'svg', 'pdf']
                fmt = input(f"Формат визуализации ({'/'.join(formats)}) [по умолчанию png]: ").strip().lower()
                fmt = fmt if fmt in formats else 'png'
                viz_path = f"{viz_base}.{fmt}"
                safe_viz = confirm_overwrite(viz_path)
                if save_visualization(np, signal, os.path.dirname(safe_viz), os.path.splitext(os.path.basename(safe_viz))[0]):
                    professional_options.append("визуализация")
                    print(f"✅ Визуализация сохранена в {safe_viz}")
                else:
                    print("❌ Не удалось сохранить визуализацию")

            # CSV
            if '2' in options:
                print("\nСохранение CSV...")
                output_csv = os.path.join(output_dir, output_filename + ".csv")
                safe_csv = confirm_overwrite(output_csv)
                try:
                    save_csv(safe_csv, signal, channels)
                    professional_options.append("CSV")
                    print(f"✅ CSV сохранен в {safe_csv}")
                except Exception as e:
                    print(f"❌ Ошибка при сохранении CSV: {e}")

            # Неконтролируемая амплитуда
            if '3' in options:
                print("\n⚠️  Неконтролируемая амплитуда (режим профессионала)")
                max_amplitude = np.max(np.abs(signal))
                if max_amplitude > 1.0:
                    print(f"❗ ВНИМАНИЕ: Амплитуда превышает 1.0! Максимум: {max_amplitude:.4f}")
                    print("Это может привести к клиппингу при воспроизведении")
                else:
                    print(f"Амплитуда в пределах: {max_amplitude:.4f}")
                print("Сигнал сохранен без дополнительной нормализации")
                professional_options.append("неконтролируемая амплитуда")

            # Видео спектрограммы (экспериментальная функция)
            if '4' in options:
                # === 🔥 ПАСХАЛКА + ТАЙМЕРЫ НЕТЕРПЕЛИВОГО РАЗРАБА ===
                if in_termux and duration >= 60:
                    print("\nох зря брат.. поймешь через пару дней")
                    time.sleep(1.5)  # драматическая пауза

                    # Создаем список реплик разработчика
                    dev_replies = [
                        "Эээ... ты ещё жив? Я просто интересуюсь, как там спектрограмма.",
                        "Ну так что? Уже всё? Или ты решил посидеть и подождать чуда?",
                        "Неужели я забыл сказать, что это может занять... эээ... вечность?",
                        "А если я сейчас закрою терминал — ты не обидишься? Просто мне надо поесть.",
                        "Знаешь, я уже начал писать тебе письмо с извинениями за эту идею...",
                        "Ты еще до живой? а твой телефон?",
                        "Ладно, я ухожу. Но если вдруг закончишь — напиши мне. Я буду ждать... в другом потоке."
                    ]

                    # Флаг для отмены таймеров
                    stop_dev_timer = False

                    def dev_message(index):
                        if stop_dev_timer:
                            return
                        if index < len(dev_replies):
                            print(f"\n💬 [Разработчик] {dev_replies[index]}")
                            # Запускаем следующий таймер (через 10 минут)
                            timer = threading.Timer(600, dev_message, args=(index + 1,))
                            timer.daemon = True
                            timer.start()
                        else:
                            # После 7 реплик — разработчик уходит
                            print("\n🚪 [Разработчик] Ушел. Надеюсь, ты не уснул. Или умер. Или просто выключил телефон.")
                            print("💡 P.S. Если хочешь, можешь запустить это на ПК. Там быстрее. И без моих сообщений.")

                    # Запускаем первый таймер (через 10 минут)
                    first_timer = threading.Timer(600, dev_message, args=(0,))
                    first_timer.daemon = True
                    first_timer.start()

                # === ГЕНЕРАЦИЯ ВИДЕО СПЕКТРОГРАММЫ ===
                print("\nГенерация видео спектрограммы...")
                spec_path = os.path.join(output_dir, f"{output_filename}_spectrogram.mp4")
                safe_spec = confirm_overwrite(spec_path)

                # Проверка наличия ffmpeg
                if not check_ffmpeg():
                    print("⚠️  ffmpeg не найден. Установите ffmpeg для создания спектрограммы.")
                    print("   На Ubuntu: sudo apt install ffmpeg")
                    print("   На Windows: https://ffmpeg.org/download.html")
                    print("   На macOS: brew install ffmpeg")
                    print("   Для Termux: pkg install ffmpeg")
                else:
                    try:
                        spec_result = save_spectrogram_video(
                            np, signal, sample_rate, output_dir,
                            output_filename, channels, hop_length=512, n_fft=2048
                        )
                        if spec_result and os.path.exists(spec_result):
                            professional_options.append("видео спектрограммы")
                            print(f"✅ Видео спектрограммы сохранено: {spec_result}")

                            # Отменяем все таймеры разработчика — работа завершена!
                            stop_dev_timer = True
                        else:
                            print("❌ Не удалось создать видео спектрограммы")
                    except Exception as e:
                        print(f"❌ Ошибка при создании видео спектрограммы: {e}")
                        import traceback
                        traceback.print_exc()
                        # Отменяем таймеры при ошибке
                        stop_dev_timer = True

        # --- ИТОГОВЫЙ ОТЧЕТ ---
        if formats_saved or professional_options:
            all_saved = formats_saved + professional_options
            print(f"\n{'='*50}")
            print("УСПЕШНО СОХРАНЕНО")
            print(f"Форматы: {', '.join(all_saved)}")
            print(f"Каталог: {output_dir}")
            print(f"Размер сигнала: {duration:.2f} сек, {sample_rate} Гц, {channels} каналов")
            print(f"Оригинальная амплитуда: {np.max(np.abs(signal)):.4f}")
            print(f"{'='*50}")
        else:
            print("\n❌ Не сохранено ни одного формата или опции")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        # Если произошла ошибка — отменяем таймеры
        try:
            stop_dev_timer = True
        except:
            pass

# ==============================================================================
# ТОЧКА ВХОДА
# ==============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем (Ctrl+C). Завершение...")
        sys.exit(0)

# Author: KADAD0F
# License: MIT
