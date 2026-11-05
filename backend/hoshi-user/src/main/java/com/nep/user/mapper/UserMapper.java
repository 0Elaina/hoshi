package com.nep.user.mapper;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.nep.user.entity.User;

@Mapper
public interface UserMapper extends BaseMapper<User> {

}
