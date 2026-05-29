# Plan Build Desktop App Đọc MRZ Passport Và Xuất Excel

## Summary

- Xây app desktop Windows bằng Python + PySide6, xử lý MRZ bằng PassportEye/Tesseract, tiền xử lý ảnh bằng OpenCV, ghi/đọc Excel bằng openpyxl.
- Workflow chính: người dùng tạo/mở workbook Excel, chọn thư mục ảnh batch, app đọc MRZ, parse thông tin, ghi vào bảng Excel trong app, rồi Save/Save As ra `.xlsx`.
- Quản lý package bằng `pyproject.toml`; dùng `make install` để chạy `uv sync` và `make build` để build app desktop.

## Key Decisions

- Excel columns v1: `STT`, `Họ tên`, `Ngày sinh`, `Giới tính`, `Số hộ chiếu`, `Ngày hết hạn`, `Ngày thêm`.
- Bỏ `Ngày cấp` vì MRZ passport không chứa dữ liệu này.
- Ngày trong Excel lưu bằng date thật và format `dd/mm/yyyy`.
- Dòng OCR lỗi hoặc checksum fail được tô đỏ.
- Batch input v1 là folder ảnh phổ biến: jpg, jpeg, png, tif, tiff, bmp, webp.
- V1 không hỗ trợ PDF và không nhúng ảnh vào Excel.

## Implementation Milestones

1. Starter repo: `.gitignore`, `README.md`, `.ai` plan, `pyproject.toml`, `Makefile`.
2. Excel workbook service.
3. MRZ OCR pipeline.
4. Batch processing.
5. PySide6 desktop UI.
6. Smoke tests.
7. Windows packaging setup.
