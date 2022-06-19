V=1

kk_dtools-$(V)-py3-none-any.whl: setup.py kk/dtools/_rio.py kk/dtools/__init__.py
	python setup.py bdist_wheel -d .

clean:
	rm -rf build dist kk_dtools-$(V)-py3-none-any.whl
