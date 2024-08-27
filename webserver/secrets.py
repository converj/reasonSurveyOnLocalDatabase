
crumbSalt         = 'CUSTOM_ALPHANUMERIC'
sessionSalt       = 'CUSTOM_ALPHANUMERIC'
voterIdSalt       = 'CUSTOM_ALPHANUMERIC'

experimentalPassword = 'CUSTOM_ALPHANUMERIC'
adminSalt = 'CUSTOM_ALPHANUMERIC'
EMAIL_SENDER_ADDRESS = 'CUSTOM@EMAIL'


from configuration import const as conf
if conf.isDev:
    import secretsDev
    experimentalPassword = secretsDev.experimentalPassword
    adminSalt = secretsDev.adminSalt
 
