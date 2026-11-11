from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, 
                             QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, 
                             QLabel, QTabWidget, QWidget, QGridLayout, QRadioButton, 
                             QMessageBox)

class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки опроса")
        layout = QFormLayout(self)

        self.spin_points = QSpinBox()
        self.spin_points.setRange(1, 1000000)
        self.spin_points.setValue(10000)
        layout.addRow("Количество точек:", self.spin_points)

        self.check_inf = QCheckBox("Бесконечно")
        layout.addRow("", self.check_inf)

        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(0.01, 10.0)
        self.spin_rate.setValue(0.1)
        self.spin_rate.setSuffix(" сек")
        layout.addRow("Интервал опроса:", self.spin_rate)

        self.check_skip = QCheckBox("Пропускать повторные показания")
        layout.addRow("", self.check_skip)

        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)

    def get_settings(self):
        return {
            "max_points": self.spin_points.value(),
            "infinite": self.check_inf.isChecked(),
            "interval": int(self.spin_rate.value() * 1000),
            "skip_repeats": self.check_skip.isChecked()
        }

class FunctionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор функции измерения")
        layout = QVBoxLayout(self)
        
        self.combo = QComboBox()
        self.combo.addItems(["Voltage DC"])
        layout.addWidget(self.combo)
        
        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

class MathDialog(QDialog):
    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Математические операции")
        self.instrument = instrument
        self.resize(400, 350)
        
        tabs = QTabWidget()
        
        # Вкладка Статистика
        tab_stat = QWidget()
        layout_stat = QVBoxLayout(tab_stat)
        self.radio_stat_on = QRadioButton("Вкл")
        self.radio_stat_off = QRadioButton("Выкл")
        self.radio_stat_off.setChecked(True)
        layout_stat.addWidget(self.radio_stat_on)
        layout_stat.addWidget(self.radio_stat_off)
        
        self.btn_read_stat = QPushButton("Прочитать статистику с прибора")
        self.btn_read_stat.clicked.connect(self.read_statistics)
        layout_stat.addWidget(self.btn_read_stat)
        
        self.lbl_stat_result = QLabel("Данные не считаны")
        layout_stat.addWidget(self.lbl_stat_result)
        
        self.btn_clear_stat = QPushButton("Очистить статистику")
        layout_stat.addWidget(self.btn_clear_stat)
        tabs.addTab(tab_stat, "Статистика")
        
        # Вкладка Пределы
        tab_lim = QWidget()
        layout_lim = QGridLayout(tab_lim)
        self.radio_lim_on = QRadioButton("Вкл")
        self.radio_lim_off = QRadioButton("Выкл")
        self.radio_lim_off.setChecked(True)
        layout_lim.addWidget(self.radio_lim_on, 0, 0)
        layout_lim.addWidget(self.radio_lim_off, 0, 1)
        
        layout_lim.addWidget(QLabel("Верхний предел:"), 1, 0)
        self.spin_upper = QDoubleSpinBox()
        self.spin_upper.setRange(-1000, 1000)
        self.spin_upper.setValue(20.0)
        layout_lim.addWidget(self.spin_upper, 1, 1)
        
        layout_lim.addWidget(QLabel("Нижний предел:"), 2, 0)
        self.spin_lower = QDoubleSpinBox()
        self.spin_lower.setRange(-1000, 1000)
        self.spin_lower.setValue(-20.0)
        layout_lim.addWidget(self.spin_lower, 2, 1)
        
        self.btn_clear_lim = QPushButton("Очистить пределы")
        layout_lim.addWidget(self.btn_clear_lim, 3, 0)
        tabs.addTab(tab_lim, "Пределы")
        
        layout_main = QVBoxLayout(self)
        layout_main.addWidget(tabs)
        
        btn_ok = QPushButton("Применить")
        btn_ok.clicked.connect(self.apply_math)
        layout_main.addWidget(btn_ok)
        
        self.btn_clear_stat.clicked.connect(lambda: self.send_cmd("CALC:AVER:CLE"))
        self.btn_clear_lim.clicked.connect(lambda: self.send_cmd("CALC:LIM:CLE"))
        
        if self.instrument:
            try:
                stat_state = self.instrument.query("CALC:AVER:STAT?").strip()
                if int(stat_state) == 1: self.radio_stat_on.setChecked(True)
                else: self.radio_stat_off.setChecked(True)
                
                lim_state = self.instrument.query("CALC:LIM:STAT?").strip()
                if int(lim_state) == 1: self.radio_lim_on.setChecked(True)
                else: self.radio_lim_off.setChecked(True)
            except: pass

    def send_cmd(self, cmd):
        if self.instrument:
            try: self.instrument.write(cmd)
            except: pass

    def read_statistics(self):
        if not self.instrument: return
        try:
            mean = self.instrument.query("CALC:AVER:AVER?").strip()
            vmax = self.instrument.query("CALC:AVER:MAX?").strip()
            vmin = self.instrument.query("CALC:AVER:MIN?").strip()
            self.lbl_stat_result.setText(f"Среднее: {mean}\nМакс: {vmax}\nМин: {vmin}")
        except Exception as e:
            self.lbl_stat_result.setText(f"Ошибка чтения: {e}")

    def apply_math(self):
        if not self.instrument: return
        try:
            if self.radio_stat_on.isChecked(): self.instrument.write("CALC:AVER:STAT ON")
            else: self.instrument.write("CALC:AVER:STAT OFF")
            
            if self.radio_lim_on.isChecked():
                self.instrument.write(f"CALC:LIM:LOW {self.spin_lower.value()}")
                self.instrument.write(f"CALC:LIM:UPP {self.spin_upper.value()}")
                self.instrument.write("CALC:LIM:STAT ON")
            else:
                self.instrument.write("CALC:LIM:STAT OFF")
            
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))