import unicodedata

def format_field(field_id: str, value: str) -> str:
    length = str(len(value.encode('utf-8'))).zfill(2)
    return f"{field_id}{length}{value}"

def calcular_crc16(payload: str) -> str:
    crc = 0xFFFF
    for char in payload:
        crc ^= (ord(char) << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return hex(crc)[2:].upper().zfill(4)

def gerar_pix_copia_e_cola(chave_pix: str, nome_recebedor: str, cidade: str, valor: float = None, txid: str = "***") -> str:
    """
    Gera o payload oficial do Banco Central (EMV QRCPS / BR Code) com CRC16.
    """
    nome_sanitizado = unicodedata.normalize('NFKD', nome_recebedor).encode('ASCII', 'ignore').decode('ASCII')[:25]
    cidade_sanitizada = unicodedata.normalize('NFKD', cidade).encode('ASCII', 'ignore').decode('ASCII')[:15]
    
    # Campo 26: Informações da conta do recebedor
    gui = format_field("00", "br.gov.bcb.pix")
    key = format_field("01", chave_pix)
    merchant_account = format_field("26", gui + key)
    
    # Campo 62: Dados adicionais
    additional_data = format_field("62", format_field("05", txid))
    
    payload_parts = [
        format_field("00", "01"),          # Formato do Payload
        merchant_account,                  # Informações do recebedor
        format_field("52", "0000"),        # Categoria do comerciante
        format_field("53", "986"),         # Moeda (986 = BRL Real)
    ]
    
    if valor and valor > 0:
        payload_parts.append(format_field("54", f"{valor:.2f}"))
        
    payload_parts.extend([
        format_field("58", "BR"),          # Código do país
        format_field("59", nome_sanitizado), # Nome do recebedor
        format_field("60", cidade_sanitizada), # Cidade
        additional_data,                   # TXID
        "6304"                             # Indicador de CRC16
    ])
    
    payload_sem_crc = "".join(payload_parts)
    crc = calcular_crc16(payload_sem_crc)
    return payload_sem_crc + crc

def gerar_url_qr_code(payload_pix: str) -> str:
    """Retorna URL para renderização direta do QR Code."""
    import urllib.parse
    encoded = urllib.parse.quote(payload_pix)
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"

