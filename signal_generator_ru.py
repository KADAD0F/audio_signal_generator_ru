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
    Проверяет наличие ffmpeg в системе через вызов 'ffmpeg -version'.
    Необходим для экспорта в MP3.
    """
    try:
        subprocess.run(['ffmpeg', '-version'],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
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
        choice = input(
            "Попробовать запросить разрешение через termux-setup-storage? (y/n): "
        ).strip().lower()

        if choice in ('y', 'yes', 'да', 'д'):
            print("Выполняется termux-setup-storage... Следуйте инструкциям на экране.")
            print("После завершения нажмите Enter, чтобы продолжить.")
            try:
                subprocess.run(['termux-setup-storage'], check=True)
            except (subprocess.SubprocessError, FileNotFoundError):
                print("⚠️  Не удалось запустить termux-setup-storage.")
                break

            input()  # Ждём подтверждения от пользователя

            # Повторная проверка
            if can_write_to(shared_dir):
                print(f"✅ Доступ получен. Файлы будут сохранены в: {shared_dir}")
                return shared_dir
            else:
                print("❌ Доступ не предоставлен. Повторите попытку или выберите локальное сохранение.")
                continue

        elif choice in ('n', 'no', 'нет', 'н'):
            print(f"📁 Используется локальная директория Termux: {local_dir}")
            return local_dir
        else:
            print("Пожалуйста, введите 'y' или 'n'.")

    # Если цикл завершился без успеха — резервный вариант
    print(f"📁 Резерв: сохранение в локальную директорию {local_dir}")
    return local_dir

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

    print("\nДобавление сигналов (оставьте пустым для завершения):")
    while True:
        signal_type = input("Тип сигнала (sin, am, pulse, noise, chm): ").strip().lower()
        if not signal_type:
            break
        if signal_type not in ['sin', 'am', 'pulse', 'noise', 'chm']:
            print("Неверный тип. Допустимые: sin, am, pulse, noise, chm")
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
    """Сохраняет сигнал в WAV-файл (16-bit PCM)."""
    data = normalize_signal(np, data)

    if hasattr(np, 'int16'):
        data_int16 = np.int16(data * 32767)
    else:
        data_int16 = (data * 32767).to(dtype=np.int16)

    with wave.open(filename, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(data_int16.tobytes())

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
    """Сохраняет сигнал в MP3 через pydub и ffmpeg."""
    data = normalize_signal(np, data)

    if hasattr(np, 'int16'):
        data_int16 = np.int16(data * 32767)
    else:
        data_int16 = (data * 32767).to(dtype=np.int16)

    audio = AudioSegment(
        data_int16.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=channels
    )
    audio.export(filename, format='mp3')

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
    5. Сохраняет в выбранных форматах
    6. (Опционально) сохраняет визуализацию
    """
    np = get_numpy_or_alternative()
    if np is None:
        print("Для работы скрипта требуется библиотека для работы с массивами. Скрипт завершен.")
        sys.exit(1)

    # Определение директории сохранения с проверкой прав
    output_dir = determine_output_directory()

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

    try:
        # Генерация сигнала
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

        if format_choice in [1, 3]:
            output_wav = os.path.join(output_dir, output_filename + ".wav")
            save_wav(np, output_wav, sample_rate, signal, channels)
            print(f"\n✅ WAV сохранен в {output_wav}")

        if format_choice in [2, 3]:
            if not check_ffmpeg():
                print("⚠️  ffmpeg не найден. Установите ffmpeg для сохранения в MP3.")
                print("   На Ubuntu: sudo apt install ffmpeg")
                print("   На Windows: https://ffmpeg.org/download.html  ")
                print("   На macOS: brew install ffmpeg")
            else:
                try:
                    from pydub import AudioSegment
                    output_mp3 = os.path.join(output_dir, output_filename + ".mp3")
                    save_mp3(np, AudioSegment, output_mp3, sample_rate, signal, channels)
                    print(f"✅ MP3 сохранен в {output_mp3}")
                except ImportError:
                    print("MP3 сохранение невозможно: pydub не установлен")

        # Сохранение CSV
        output_csv = os.path.join(output_dir, output_filename + ".csv")
        save_csv(output_csv, signal, channels)
        print(f"CSV сохранен в {output_csv}")

        # Визуализация (опционально)
        save_viz = input("\nСохранить визуализацию сигнала? (y/n): ")
        if is_yes(save_viz):
            save_visualization(np, signal, output_dir, output_filename)

    except Exception as e:
        print(f"❌ Ошибка: {e}")

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